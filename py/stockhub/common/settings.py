"""Application settings, read from environment variables (and the repo-root .env in dev).

Missing or invalid required settings fail fast with a message naming every offending
variable, so a misconfigured Cloud Run Job dies on start instead of halfway through a run.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# py/stockhub/common/settings.py -> repo root is three levels up from this package.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = PROJECT_ROOT / ".env"

CommaList = Annotated[list[str], NoDecode]


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = Field(min_length=1)

    rawstore_backend: Literal["local", "gcs"] = "local"
    rawstore_local_dir: Path = Path(".local/rawstore")
    rawstore_gcs_bucket: str | None = None

    notifier: Literal["console", "email"] = "console"
    alert_email_to: CommaList = Field(default_factory=list)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    providers_price: CommaList = Field(default_factory=lambda: ["twse", "tpex"])
    providers_financial: CommaList = Field(default_factory=list)
    providers_quote: CommaList = Field(default_factory=list)
    providers_calendar: CommaList = Field(default_factory=lambda: ["twse"])
    providers_securities: CommaList = Field(default_factory=lambda: ["twse"])
    providers_delistings: CommaList = Field(default_factory=lambda: ["twse", "tpex"])

    @field_validator(
        "alert_email_to",
        "providers_price",
        "providers_financial",
        "providers_quote",
        "providers_calendar",
        "providers_securities",
        "providers_delistings",
        mode="before",
    )
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "rawstore_gcs_bucket", "smtp_host", "smtp_username", "smtp_from", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("rawstore_local_dir")
    @classmethod
    def _resolve_local_dir(cls, value: Path) -> Path:
        # Relative paths are relative to the repo root (when running from a checkout),
        # so `make` targets that cd into py/ still share one .local/rawstore directory.
        if value.is_absolute():
            return value
        base = PROJECT_ROOT if (PROJECT_ROOT / "db" / "migrations").is_dir() else Path.cwd()
        return (base / value).resolve()

    @model_validator(mode="after")
    def _check_backends(self) -> Self:
        missing: list[str] = []
        if self.rawstore_backend == "gcs" and not self.rawstore_gcs_bucket:
            missing.append("RAWSTORE_GCS_BUCKET (required when RAWSTORE_BACKEND=gcs)")
        if self.notifier == "email":
            for name in ("smtp_host", "smtp_from"):
                if not getattr(self, name):
                    missing.append(f"{name.upper()} (required when NOTIFIER=email)")
            if not self.alert_email_to:
                missing.append("ALERT_EMAIL_TO (required when NOTIFIER=email)")
        if missing:
            raise ValueError("missing settings: " + "; ".join(missing))
        return self


def load_settings(**overrides: object) -> Settings:
    """Build settings, converting validation errors into one readable ConfigError."""
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            field = ".".join(str(part) for part in err["loc"]).upper() or "SETTINGS"
            if err["type"] == "missing":
                problems.append(f"{field}: required environment variable is not set")
            else:
                problems.append(f"{field}: {err['msg']}")
        raise ConfigError(
            "Invalid configuration (see .env.example):\n  - " + "\n  - ".join(problems)
        ) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return load_settings()
