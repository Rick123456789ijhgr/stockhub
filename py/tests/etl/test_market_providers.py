"""Market series sources (M5): TWSE/TPEx indices, Yahoo, FRED, NDC; parsing and checks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine

from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.providers.base import (
    AllProvidersFailedError,
    PermanentProviderError,
    RawResponse,
    SeriesObservation,
)
from stockhub.etl.providers.fred import FredProvider
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.ndc import NdcProvider
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider
from stockhub.etl.providers.yahoo import YahooProvider
from stockhub.etl.quality import check_series_observation

from .official_sources import fixture, official_handler, official_router

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def _client() -> httpx.Client:
    return make_client(httpx.MockTransport(official_handler))


def test_taiex_month_from_twse() -> None:
    twse = TwseProvider(_client())
    raw = twse.fetch_market_series("TAIEX", *OCT)
    assert raw.params == {"code": "TAIEX", "start": "2026-10-01", "end": "2026-10-31"}
    bars = twse.parse_market_series(raw)
    assert len(bars) == 13
    assert bars[0] == SeriesObservation(
        code="TAIEX",
        obs_date=date(2026, 10, 1),
        open=Decimal("47961.98"),
        high=Decimal("48353.49"),
        low=Decimal("47893.42"),
        value=Decimal("48353.49"),
    )
    assert bars[-1].obs_date == date(2026, 10, 20)
    # A narrower range keeps only its days; a month without data is empty, not an error.
    narrow = twse.parse_market_series(twse.fetch_market_series("TAIEX", OCT[0], date(2026, 10, 2)))
    assert [b.obs_date.day for b in narrow] == [1, 2]
    assert (
        twse.parse_market_series(
            twse.fetch_market_series("TAIEX", date(2030, 1, 1), date(2030, 1, 31))
        )
        == []
    )


def test_index_providers_refuse_multi_month_ranges_and_other_codes() -> None:
    twse, tpex = TwseProvider(_client()), TpexProvider(_client())
    with pytest.raises(PermanentProviderError):
        twse.fetch_market_series("TAIEX", date(2026, 9, 1), date(2026, 10, 31))
    with pytest.raises(PermanentProviderError):
        tpex.fetch_market_series("TAIEX", *OCT)


def test_tpex_index_month() -> None:
    tpex = TpexProvider(_client())
    bars = tpex.parse_market_series(tpex.fetch_market_series("TPEX", *OCT))
    assert len(bars) == 13
    last = bars[-1]
    assert (last.obs_date, last.open, last.value) == (
        date(2026, 10, 20),
        Decimal("393.73"),
        Decimal("387.88"),
    )
    assert (
        tpex.parse_market_series(
            tpex.fetch_market_series("TPEX", date(2030, 1, 1), date(2030, 1, 31))
        )
        == []
    )


def _yahoo_raw(fetched_at: datetime) -> RawResponse:
    return RawResponse(
        "chart",
        fixture("yahoo_chart_gspc.json"),
        {
            "code": "SPX",
            "symbol": "^GSPC",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "fetched_at": fetched_at.isoformat(),
        },
    )


def test_yahoo_dates_bars_in_exchange_time_and_rounds_floats() -> None:
    yahoo = YahooProvider(_client())
    bars = yahoo.parse_market_series(_yahoo_raw(datetime(2026, 10, 21, 2, 0, tzinfo=UTC)))
    assert bars[0].obs_date == date(2026, 10, 1)  # 2026-09-30 is outside the range
    assert bars[0].value == Decimal("7666.4502")
    assert bars[-1].obs_date == date(2026, 10, 20)
    assert len(bars) == 14


def test_yahoo_drops_the_bar_of_a_session_still_open() -> None:
    yahoo = YahooProvider(_client())
    during = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)  # 11:00 in New York
    bars = yahoo.parse_market_series(_yahoo_raw(during))
    assert bars[-1].obs_date == date(2026, 10, 19)


def test_yahoo_fetch_params_and_unknown_symbol() -> None:
    yahoo = YahooProvider(_client())
    raw = yahoo.fetch_market_series("SPX", *OCT)
    assert raw.params["symbol"] == "^GSPC"
    with pytest.raises(PermanentProviderError):
        yahoo.fetch_market_series("SOX", *OCT)  # the mock answers 404 like Yahoo
    with pytest.raises(PermanentProviderError):
        yahoo.fetch_market_series("UST10Y", *OCT)


def test_fred_csv() -> None:
    fred = FredProvider(_client())
    raw = fred.fetch_market_series("UST10Y", date(2026, 10, 1), date(2026, 10, 2))
    assert raw.params["symbol"] == "DGS10"
    assert fred.parse_market_series(raw) == [
        SeriesObservation(code="UST10Y", obs_date=date(2026, 10, 1), value=Decimal("5.24")),
        SeriesObservation(code="UST10Y", obs_date=date(2026, 10, 2), value=Decimal("5.28")),
    ]
    blanks = RawResponse(
        "fredgraph",
        b"observation_date,DGS10\n2026-10-01,.\n2026-10-02,\n2026-10-05,5.31\n",
        {"code": "UST10Y", "symbol": "DGS10", "start": "2026-10-01", "end": "2026-10-31"},
    )
    assert [o.obs_date.day for o in fred.parse_market_series(blanks)] == [5]
    wrong = RawResponse("fredgraph", b"observation_date,DGS2\n", dict(blanks.params))
    with pytest.raises(ValueError, match="header"):
        fred.parse_market_series(wrong)


def test_ndc_release_follows_the_data_set_metadata() -> None:
    ndc = NdcProvider(_client())
    raw = ndc.fetch_macro_release()
    assert raw.params["url"].startswith("https://ws.ndc.gov.tw/Download.ashx")
    obs = ndc.parse_macro_release(raw)
    by_key = {(o.code, o.obs_date): o for o in obs}
    august = by_key[("TW_SIGNAL", date(2026, 8, 1))]
    assert (august.value, august.label) == (Decimal(41), "紅燈")
    assert by_key[("TW_LEADING", date(2026, 8, 1))].value == Decimal("104.4086599")
    assert by_key[("TW_COINCIDENT", date(2026, 8, 1))].value == Decimal("106.4711496")
    # The signal started in 1984; earlier months carry only the indices.
    assert ("TW_SIGNAL", date(1982, 1, 1)) not in by_key
    assert ("TW_LEADING", date(1982, 1, 1)) in by_key
    assert {o.label for o in obs if o.code == "TW_SIGNAL"} == {
        "紅燈",
        "黃紅燈",
        "綠燈",
        "黃藍燈",
        "藍燈",
    }


def test_router_falls_back_and_respects_monthly_sources(clean_db: Engine, tmp_path: Path) -> None:
    router = official_router(LocalRawStore(clean_db, tmp_path))
    assert router.series_monthly("TAIEX")
    assert not router.series_monthly("SPX")
    assert [p.name for p in router.series_providers("SPX")] == ["yahoo", "fred"]
    fetched = router.market_series("SPX", *OCT)
    assert fetched.provider == "yahoo"
    fallback = router.market_series("N225", *OCT)
    assert fallback.provider == "fred"
    assert fallback.used_fallback
    month = router.market_series("TAIEX", *OCT)
    assert month.provider == "twse"
    # Two months skip the monthly TWSE source and ask Yahoo (404 in the mock).
    with pytest.raises(AllProvidersFailedError) as failed:
        router.market_series("TAIEX", date(2026, 9, 1), OCT[1])
    assert [a.provider for a in failed.value.attempts] == ["yahoo"]


def _obs(
    value: str, open: str | None = None, high: str | None = None, low: str | None = None
) -> SeriesObservation:
    def num(text: str | None) -> Decimal | None:
        return Decimal(text) if text is not None else None

    return SeriesObservation(
        code="X",
        obs_date=date(2026, 10, 1),
        value=Decimal(value),
        open=num(open),
        high=num(high),
        low=num(low),
    )


def test_series_quality_checks() -> None:
    def check(obs: SeriesObservation, previous: str | None = None, **kw: object) -> list[str]:
        options = {"positive": True, "max_move": Decimal("0.15")} | kw
        prev = Decimal(previous) if previous else None
        return check_series_observation(obs, prev, **options)  # type: ignore[arg-type]

    assert check(_obs("100", open="99", high="101", low="98"), "95") == []
    assert check(_obs("100", open="102", high="101", low="98")) == ["ohlc_inconsistent"]
    assert check(_obs("100", high="90", low="98")) == ["ohlc_inconsistent"]
    assert check(_obs("0")) == ["not_positive"]
    assert check(_obs("-37.63"), positive=False, max_move=None) == []
    assert check(_obs("120"), "100") == ["move_too_large"]
    assert check(_obs("120"), "100", max_move=None) == []
