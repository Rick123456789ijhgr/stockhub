"""CLI: python -m stockhub.etl list | notify-test | drain-requests
                         | run <job> [--date YYYY-MM-DD] [--param k=v ...]

Exit codes: 0 succeeded/skipped, 1 failed, 2 usage/config error, 3 already running.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date

from stockhub.common.db import get_engine
from stockhub.common.notifier import build_notifier
from stockhub.common.rawstore import build_rawstore
from stockhub.common.settings import ConfigError, Settings, get_settings
from stockhub.etl.job_requests import drain
from stockhub.etl.jobs.base import (
    JobAlreadyRunningError,
    UnknownJobError,
    registered_jobs,
    run_job,
)
from stockhub.etl.providers.registry import ProviderRegistry
from stockhub.etl.providers.router import ProviderRouter


def _param(value: str) -> tuple[str, str]:
    key, sep, val = value.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected k=v, got {value!r}")
    return key, val


def _date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m stockhub.etl", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list available jobs")
    sub.add_parser("notify-test", help="send a test message through the configured notifier")
    sub.add_parser("drain-requests", help="run the jobs queued from the website (job_requests)")
    run = sub.add_parser("run", help="run a job and record it in job_runs")
    run.add_argument("job")
    run.add_argument("--date", type=_date, help="Taipei trading date (default: today)")
    run.add_argument("--param", type=_param, action="append", default=[], metavar="K=V")
    run.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        for name, job in registered_jobs().items():
            print(f"{name:<20} {job.description}")
        return 0

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "notify-test":
        return notify_test(settings)

    engine = get_engine()
    rawstore = build_rawstore(engine, settings)
    notifier = build_notifier(settings)
    router = ProviderRouter(ProviderRegistry.from_settings(settings), rawstore)

    if args.command == "drain-requests":
        ran = drain(
            engine,
            lambda job, params: run_job(
                job,
                params,
                "manual",
                engine=engine,
                rawstore=rawstore,
                notifier=notifier,
                router=router,
            ),
        )
        print(f"drain-requests: ran {ran} request(s)")
        return 0

    params = dict(args.param)
    if args.date:
        params["date"] = args.date
    try:
        result = run_job(
            args.job,
            params,
            args.trigger,
            engine=engine,
            rawstore=rawstore,
            notifier=notifier,
            router=router,
        )
    except UnknownJobError as exc:
        print(exc, file=sys.stderr)
        return 2
    except JobAlreadyRunningError as exc:
        print(exc, file=sys.stderr)
        return 3

    print(
        f"{result.job_name} #{result.run_id} {result.status} "
        f"rows_written={result.rows_written}"
        + (f"\n{result.message}" if result.message and result.status != "skipped" else "")
        + (f"\n{result.error}" if result.error else "")
    )
    return 1 if result.status == "failed" else 0


def notify_test(settings: Settings) -> int:
    """Send one message through NOTIFIER (console or email) to check the setup."""
    target = (
        f"email {', '.join(settings.alert_email_to)} via {settings.smtp_host}:{settings.smtp_port}"
        if settings.notifier == "email"
        else "console"
    )
    try:
        build_notifier(settings).send(
            "[StockHub] 通知測試",
            "這是一封測試通知。收到代表持股警示與任務失敗通知的寄送設定正確。",
            "info",
        )
    except Exception as exc:  # SMTP auth / TLS / network errors: show them plainly
        print(f"notify-test failed ({target}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"notify-test sent ({target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
