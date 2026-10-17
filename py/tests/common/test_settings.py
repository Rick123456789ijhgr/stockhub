from __future__ import annotations

from pathlib import Path

import pytest

from stockhub.common.settings import PROJECT_ROOT, ConfigError, Settings, load_settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore the developer's .env and any inherited variables."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(Settings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)


def test_missing_database_url_names_the_variable() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL: required environment variable"):
        load_settings()


def test_defaults_and_comma_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("PROVIDERS_PRICE", "twse, finmind ,")
    s = load_settings()
    assert s.providers_price == ["twse", "finmind"]
    assert s.providers_quote == []
    assert s.rawstore_backend == "local"
    assert s.rawstore_local_dir == (PROJECT_ROOT / ".local" / "raw").resolve()


def test_absolute_rawstore_dir_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("RAWSTORE_LOCAL_DIR", str(tmp_path))
    assert load_settings().rawstore_local_dir == tmp_path


def test_gcs_backend_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("RAWSTORE_BACKEND", "gcs")
    monkeypatch.setenv("RAWSTORE_GCS_BUCKET", "  ")
    with pytest.raises(ConfigError, match="RAWSTORE_GCS_BUCKET"):
        load_settings()


def test_email_notifier_requires_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("NOTIFIER", "email")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    for name in ("SMTP_HOST", "SMTP_FROM", "ALERT_EMAIL_TO"):
        assert name in str(exc.value)


def test_invalid_choice_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("NOTIFIER", "pigeon")
    with pytest.raises(ConfigError, match="NOTIFIER"):
        load_settings()
