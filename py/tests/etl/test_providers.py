from __future__ import annotations

import ast
import logging
import random
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import Engine, text

from stockhub.common.rawstore import LocalRawStore
from stockhub.common.settings import ConfigError, load_settings
from stockhub.etl.providers import (
    AllProvidersFailedError,
    DailyBar,
    PriceProvider,
    ProviderRegistry,
    ProviderRouter,
    RateLimiter,
    RawResponse,
    RetryPolicy,
)
from stockhub.etl.providers.fake import FakePriceProvider, FlakyFakeProvider

START, END = date(2026, 10, 12), date(2026, 10, 16)  # Mon..Fri

RouterFactory = Callable[..., ProviderRouter]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_router(clean_db: Engine, tmp_path: Path, clock: FakeClock) -> RouterFactory:
    store = LocalRawStore(clean_db, tmp_path)

    def build(*providers: PriceProvider, retry: RetryPolicy | None = None) -> ProviderRouter:
        return ProviderRouter(
            ProviderRegistry({"price": list(providers)}),
            store,
            retry=retry or RetryPolicy(max_attempts=3, base_delay=1.0, jitter=0.0),
            limiter=RateLimiter(clock=clock, sleep=clock.sleep),
            sleep=clock.sleep,
        )

    return build


def _raw_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM raw_objects")).scalar_one())


def test_primary_success_lands_raw_and_parses(make_router: RouterFactory, clean_db: Engine) -> None:
    router = make_router(FakePriceProvider(), FlakyFakeProvider(fail_rate=1.0))
    fetched = router.daily_prices(START, END, ["2330"])
    assert fetched.provider == "fake"
    assert not fetched.used_fallback
    assert [b.trade_date.day for b in fetched.items] == [12, 13, 14, 15, 16]
    assert all(isinstance(b, DailyBar) for b in fetched.items)
    assert fetched.raw.created
    assert _raw_count(clean_db) == 1


def test_transient_errors_are_retried_with_exponential_backoff(
    make_router: RouterFactory, clock: FakeClock
) -> None:
    flaky = FlakyFakeProvider(fail_first=2)
    fetched = make_router(flaky).daily_prices(START, END)
    assert fetched.provider == "flaky_fake"
    assert flaky.calls == 3
    assert [a.attempt for a in fetched.attempts] == [1, 2]
    assert clock.sleeps == [1.0, 2.0]


def test_primary_exhausting_retries_falls_back(
    make_router: RouterFactory, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    flaky = FlakyFakeProvider(fail_rate=1.0)
    with caplog.at_level(logging.WARNING):
        fetched = make_router(flaky, FakePriceProvider()).daily_prices(START, END)
    assert fetched.provider == "fake"
    assert fetched.used_fallback
    assert flaky.calls == 3
    assert [(a.provider, a.attempt) for a in fetched.attempts] == [
        ("flaky_fake", 1),
        ("flaky_fake", 2),
        ("flaky_fake", 3),
    ]
    assert clock.sleeps == [1.0, 2.0]  # no sleep after the final attempt
    assert "falling back to fake" in caplog.text


def test_permanent_error_skips_retries(make_router: RouterFactory, clock: FakeClock) -> None:
    flaky = FlakyFakeProvider(fail_rate=1.0, permanent=True)
    fetched = make_router(flaky, FakePriceProvider()).daily_prices(START, END)
    assert fetched.provider == "fake"
    assert flaky.calls == 1
    assert clock.sleeps == []


def test_all_providers_failing_raises_clear_error(make_router: RouterFactory) -> None:
    router = make_router(
        FlakyFakeProvider(fail_rate=1.0), FlakyFakeProvider(fail_rate=1.0, permanent=True)
    )
    with pytest.raises(AllProvidersFailedError) as exc:
        router.daily_prices(START, END)
    assert exc.value.kind == "price"
    assert len(exc.value.attempts) == 4
    message = str(exc.value)
    assert message.startswith("all price providers failed (flaky_fake#1: TransientProviderError")
    assert "permanent: flaky_fake: simulated failure" in message


class BrokenParser(FakePriceProvider):
    name: ClassVar[str] = "broken"

    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        raise KeyError("close")


def test_parse_error_keeps_raw_and_falls_back(make_router: RouterFactory, clean_db: Engine) -> None:
    fetched = make_router(BrokenParser(), FakePriceProvider()).daily_prices(START, END, ["0050"])
    assert fetched.provider == "fake"
    assert fetched.attempts[0].error.startswith("parse: KeyError")
    # Both providers produced the same payload: stored once, still recoverable.
    assert _raw_count(clean_db) == 1


class SlowSource(FakePriceProvider):
    name: ClassVar[str] = "slow"
    min_interval: ClassVar[float] = 0.5


def test_rate_limit_spaces_calls_per_provider(make_router: RouterFactory, clock: FakeClock) -> None:
    router = make_router(SlowSource())
    router.daily_prices(START, START)
    router.daily_prices(START, START)
    clock.now += 2.0
    router.daily_prices(START, START)
    assert clock.sleeps == [0.5]


def test_rate_limiter_is_per_provider() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    limiter.wait("a", 1.0)
    limiter.wait("b", 1.0)
    clock.now += 0.25
    limiter.wait("a", 1.0)
    assert clock.sleeps == [0.75]


def test_backoff_is_capped_and_jittered() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=3.0, jitter=0.0)
    rng = random.Random(1)
    assert [policy.delay(n, rng) for n in (1, 2, 3, 4)] == [1.0, 2.0, 3.0, 3.0]
    jittered = RetryPolicy(base_delay=1.0, jitter=0.5).delay(1, rng)
    assert 1.0 <= jittered <= 1.5


def test_flaky_fail_rate_is_seeded() -> None:
    def failures(seed: int) -> list[bool]:
        p = FlakyFakeProvider(fail_rate=0.5, seed=seed)
        out = []
        for _ in range(20):
            try:
                p.fetch_daily_prices(START, START)
                out.append(False)
            except Exception:
                out.append(True)
        return out

    assert failures(7) == failures(7)
    assert 0 < sum(failures(7)) < 20
    with pytest.raises(ValueError, match="fail_rate"):
        FlakyFakeProvider(fail_rate=1.5)


def test_registry_from_names_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry.from_names({"price": ["flaky_fake", "fake"]})
    assert [p.name for p in registry.providers_for("price")] == ["flaky_fake", "fake"]

    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/db")
    monkeypatch.setenv("PROVIDERS_PRICE", "fake")
    registry = ProviderRegistry.from_settings(load_settings())
    assert [p.name for p in registry.providers_for("price")] == ["fake"]
    with pytest.raises(ConfigError, match="PROVIDERS_QUOTE"):
        registry.providers_for("quote")


def test_registry_rejects_unknown_or_incapable_providers() -> None:
    with pytest.raises(ConfigError, match="unknown provider 'twse'"):
        ProviderRegistry.from_names({"price": ["twse"]})
    with pytest.raises(ConfigError, match="cannot serve quote data"):
        ProviderRegistry.from_names({"quote": ["fake"]})


# Third-party data source packages may only be imported inside stockhub/etl/providers.
DATA_SOURCE_PACKAGES = {"twstock", "yfinance", "finmind", "FinMind"}


def test_data_source_packages_are_only_imported_by_providers() -> None:
    package_root = Path(__file__).resolve().parents[2] / "stockhub"
    offenders = []
    for path in package_root.rglob("*.py"):
        if "providers" in path.relative_to(package_root).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}: {n}" for n in names if n.split(".")[0] in DATA_SOURCE_PACKAGES
            ]
    assert offenders == []
