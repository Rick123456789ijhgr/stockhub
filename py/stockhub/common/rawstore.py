"""RawStore: land every provider response before parsing it (CLAUDE.md rule 5).

Objects live at raw/{provider}/{dataset}/{yyyy}/{mm}/{dd}/{sha256}.json.gz (UTC fetch date)
and are registered in raw_objects. Identical payloads (same SHA-256 of the uncompressed
bytes) are stored and registered once.

Registration commits on its own connection, independent of the caller's transaction, so the
raw object survives even when the job that fetched it later fails while parsing.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, text

from stockhub.common.timeutil import utcnow

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

    from stockhub.common.settings import Settings

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


@dataclass(frozen=True)
class RawObject:
    id: int
    uri: str
    sha256: str
    bytes: int
    created: bool
    """False when an identical payload was already stored."""


def encode_payload(payload: bytes | str | Any) -> bytes:
    """Bytes pass through; str is UTF-8; anything else is serialized as JSON."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode()


def object_key(provider: str, dataset: str, fetched_at: datetime, sha256: str) -> str:
    for label, value in (("provider", provider), ("dataset", dataset)):
        if not _NAME_RE.match(value):
            raise ValueError(f"invalid {label} name for RawStore path: {value!r}")
    day = fetched_at.astimezone(UTC)
    return f"raw/{provider}/{dataset}/{day:%Y}/{day:%m}/{day:%d}/{sha256}.json.gz"


class RawStore(ABC):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def put(
        self,
        provider: str,
        dataset: str,
        payload: bytes | str | Any,
        params: dict[str, Any] | None = None,
        fetched_at: datetime | None = None,
    ) -> RawObject:
        data = encode_payload(payload)
        sha = hashlib.sha256(data).hexdigest()

        existing = self._lookup(sha)
        if existing is not None:
            return existing

        fetched_at = fetched_at or utcnow()
        key = object_key(provider, dataset, fetched_at, sha)
        if not self._exists(key):
            self._write(key, gzip.compress(data, mtime=0))

        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO raw_objects (provider, dataset, params, uri, sha256, bytes, "
                    "fetched_at) VALUES (:provider, :dataset, CAST(:params AS jsonb), :uri, "
                    ":sha256, :bytes, :fetched_at) ON CONFLICT (sha256) DO NOTHING RETURNING id"
                ),
                {
                    "provider": provider,
                    "dataset": dataset,
                    "params": json.dumps(params or {}, default=str),
                    "uri": self.uri_for(key),
                    "sha256": sha,
                    "bytes": len(data),
                    "fetched_at": fetched_at,
                },
            ).first()
        if row is None:  # lost a race with a concurrent writer of the same payload
            raced = self._lookup(sha)
            if raced is None:
                raise RuntimeError(f"raw object {sha} vanished during registration")
            return raced
        return RawObject(int(row[0]), self.uri_for(key), sha, len(data), created=True)

    def get(self, uri: str) -> bytes:
        """Return the uncompressed payload, verifying it against its content hash."""
        key = self.key_for(uri)
        data = gzip.decompress(self._read(key))
        expected = Path(key).name.removesuffix(".json.gz")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"raw object {uri} is corrupt (hash mismatch)")
        return data

    def delete(self, raw_object_id: int) -> bool:
        """Remove one object and its registration (retention of social posts, D-138).
        References in news_items are cleared by ON DELETE SET NULL; False if unknown."""
        with self._engine.begin() as conn:
            uri = conn.execute(
                text("DELETE FROM raw_objects WHERE id = :id RETURNING uri"), {"id": raw_object_id}
            ).scalar_one_or_none()
        if uri is None:
            return False
        self._delete(self.key_for(uri))
        return True

    def _lookup(self, sha: str) -> RawObject | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, uri, bytes FROM raw_objects WHERE sha256 = :sha"), {"sha": sha}
            ).first()
        if row is None:
            return None
        return RawObject(int(row.id), row.uri, sha, int(row.bytes), created=False)

    @abstractmethod
    def uri_for(self, key: str) -> str: ...

    @abstractmethod
    def key_for(self, uri: str) -> str: ...

    @abstractmethod
    def _exists(self, key: str) -> bool: ...

    @abstractmethod
    def _write(self, key: str, blob: bytes) -> None: ...

    @abstractmethod
    def _read(self, key: str) -> bytes: ...

    @abstractmethod
    def _delete(self, key: str) -> None:
        """Remove the stored blob; a missing blob is not an error."""


class LocalRawStore(RawStore):
    """Filesystem backend for development and tests."""

    def __init__(self, engine: Engine, root: Path) -> None:
        super().__init__(engine)
        self.root = root.resolve()

    def uri_for(self, key: str) -> str:
        return (self.root / key).as_uri()

    def key_for(self, uri: str) -> str:
        prefix = self.root.as_uri() + "/"
        if not uri.startswith(prefix):
            raise ValueError(f"{uri} is not under {prefix}")
        return uri[len(prefix) :]

    def _exists(self, key: str) -> bool:
        return (self.root / key).is_file()

    def _write(self, key: str, blob: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, path)  # atomic: readers never see a partial file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def _delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


class GCSRawStore(RawStore):
    """Google Cloud Storage backend (credentials via Application Default Credentials)."""

    def __init__(self, engine: Engine, bucket: Bucket) -> None:
        super().__init__(engine)
        self.bucket = bucket

    @classmethod
    def from_bucket_name(cls, engine: Engine, bucket_name: str) -> GCSRawStore:
        from google.cloud import storage

        return cls(engine, storage.Client().bucket(bucket_name))

    def uri_for(self, key: str) -> str:
        return f"gs://{self.bucket.name}/{key}"

    def key_for(self, uri: str) -> str:
        prefix = f"gs://{self.bucket.name}/"
        if not uri.startswith(prefix):
            raise ValueError(f"{uri} is not in bucket {self.bucket.name}")
        return uri[len(prefix) :]

    def _exists(self, key: str) -> bool:
        return bool(self.bucket.blob(key).exists())

    def _write(self, key: str, blob: bytes) -> None:
        from google.api_core.exceptions import PreconditionFailed

        # if_generation_match=0: never overwrite (content-addressed, so same bytes anyway).
        with contextlib.suppress(PreconditionFailed):
            self.bucket.blob(key).upload_from_string(
                blob, content_type="application/gzip", if_generation_match=0
            )

    def _read(self, key: str) -> bytes:
        return bytes(self.bucket.blob(key).download_as_bytes())

    def _delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        with contextlib.suppress(NotFound):
            self.bucket.blob(key).delete()


def build_rawstore(engine: Engine, settings: Settings) -> RawStore:
    if settings.rawstore_backend == "gcs":
        if not settings.rawstore_gcs_bucket:
            raise ValueError("RAWSTORE_BACKEND=gcs requires RAWSTORE_GCS_BUCKET")
        return GCSRawStore.from_bucket_name(engine, settings.rawstore_gcs_bucket)
    return LocalRawStore(engine, settings.rawstore_local_dir)
