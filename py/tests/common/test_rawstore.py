from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from stockhub.common.rawstore import GCSRawStore, LocalRawStore, RawStore, object_key

FETCHED_AT = datetime(2026, 10, 17, 23, 30, tzinfo=UTC)


def _raw_rows(engine: Engine) -> list[tuple[str, str, int]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT dataset, uri, bytes FROM raw_objects ORDER BY id"))
        return [(r.dataset, r.uri, r.bytes) for r in rows]


def test_object_key_layout() -> None:
    sha = "ab" * 32
    assert object_key("twse", "prices_daily", FETCHED_AT, sha) == (
        f"raw/twse/prices_daily/2026/10/17/{sha}.json.gz"
    )
    with pytest.raises(ValueError, match="provider"):
        object_key("../etc", "x", FETCHED_AT, sha)


def test_local_put_registers_and_stores_gzip(clean_db: Engine, tmp_path: Path) -> None:
    store = LocalRawStore(clean_db, tmp_path)
    payload = {"symbol": "2330", "close": "1005.0", "name": "台積電"}
    obj = store.put("fake", "prices", payload, params={"date": "2026-10-17"}, fetched_at=FETCHED_AT)

    assert obj.created
    files = list(tmp_path.rglob("*.json.gz"))
    assert len(files) == 1
    assert files[0].relative_to(tmp_path).as_posix() == (
        f"raw/fake/prices/2026/10/17/{obj.sha256}.json.gz"
    )
    data = gzip.decompress(files[0].read_bytes())
    assert hashlib.sha256(data).hexdigest() == obj.sha256
    assert "台積電".encode() in data
    assert store.get(obj.uri) == data
    assert _raw_rows(clean_db) == [("prices", obj.uri, len(data))]


def test_duplicate_payload_is_stored_once(clean_db: Engine, tmp_path: Path) -> None:
    store = LocalRawStore(clean_db, tmp_path)
    first = store.put("fake", "prices", b'{"a":1}', fetched_at=FETCHED_AT)
    # Same bytes on a later day with other params: reuse the original object.
    again = store.put("fake", "prices", b'{"a":1}', params={"retry": True})
    other = store.put("fake", "prices", b'{"a":2}', fetched_at=FETCHED_AT)

    assert (again.id, again.uri, again.created) == (first.id, first.uri, False)
    assert other.id != first.id
    assert len(list(tmp_path.rglob("*.json.gz"))) == 2
    assert len(_raw_rows(clean_db)) == 2


def test_registration_survives_caller_rollback(clean_db: Engine, tmp_path: Path) -> None:
    store = LocalRawStore(clean_db, tmp_path)
    with clean_db.connect() as conn:
        trans = conn.begin()
        store.put("fake", "prices", b"[]")
        trans.rollback()  # e.g. the job failed while parsing
    assert len(_raw_rows(clean_db)) == 1


def test_get_detects_corruption(clean_db: Engine, tmp_path: Path) -> None:
    store = LocalRawStore(clean_db, tmp_path)
    obj = store.put("fake", "prices", b"original", fetched_at=FETCHED_AT)
    path = next(tmp_path.rglob("*.json.gz"))
    path.write_bytes(gzip.compress(b"tampered"))
    with pytest.raises(ValueError, match="corrupt"):
        store.get(obj.uri)


class _FakeBlob:
    def __init__(self, bucket: _FakeBucket, name: str) -> None:
        self.bucket, self.name = bucket, name

    def exists(self) -> bool:
        return self.name in self.bucket.objects

    def upload_from_string(self, data: bytes, content_type: str, if_generation_match: int) -> None:
        assert if_generation_match == 0
        assert content_type == "application/gzip"
        self.bucket.uploads += 1
        self.bucket.objects[self.name] = data

    def download_as_bytes(self) -> bytes:
        return self.bucket.objects[self.name]


class _FakeBucket:
    name = "stockhub-raw-test"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads = 0

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)


def test_gcs_put_and_get(clean_db: Engine) -> None:
    bucket = _FakeBucket()
    store: RawStore = GCSRawStore(clean_db, bucket)
    obj = store.put("fake", "prices", {"x": 1}, fetched_at=FETCHED_AT)
    store.put("fake", "prices", {"x": 1}, fetched_at=FETCHED_AT)

    assert obj.uri == f"gs://stockhub-raw-test/raw/fake/prices/2026/10/17/{obj.sha256}.json.gz"
    assert bucket.uploads == 1
    assert store.get(obj.uri) == b'{"x":1}'
