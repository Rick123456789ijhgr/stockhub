from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import run_job
from stockhub.etl.jobs.maintenance import in_maintenance_window


def test_maintenance_window_avoids_trading_and_etl_hours() -> None:
    # Taipei is UTC+8; 2026-10-22 is a Thursday, 2026-10-24 a Saturday.
    assert in_maintenance_window(datetime(2026, 10, 21, 18, 0, tzinfo=UTC))  # Thu 02:00
    assert not in_maintenance_window(datetime(2026, 10, 21, 23, 0, tzinfo=UTC))  # Thu 07:00
    assert not in_maintenance_window(datetime(2026, 10, 22, 14, 29, tzinfo=UTC))  # Thu 22:29
    assert in_maintenance_window(datetime(2026, 10, 22, 14, 30, tzinfo=UTC))  # Thu 22:30
    assert in_maintenance_window(datetime(2026, 10, 24, 4, 0, tzinfo=UTC))  # Sat 12:00


def test_cluster_tables_rewrites_marked_tables(clean_db: Engine, tmp_path: Path) -> None:
    result = run_job(
        "cluster_tables",
        {"force": "true"},
        engine=clean_db,
        rawstore=LocalRawStore(clean_db, tmp_path),
        notifier=ConsoleNotifier(),
    )
    assert result.status == "succeeded"
    assert result.message == "clustered 9 tables"
