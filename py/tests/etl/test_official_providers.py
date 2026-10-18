from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from stockhub.etl.providers.base import (
    PermanentProviderError,
    RawResponse,
    TransientProviderError,
)
from stockhub.etl.providers.http import clean_number, make_client
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider

from .official_sources import fixture, official_handler

DAY = date(2026, 10, 16)


def _providers(handler=official_handler) -> tuple[TwseProvider, TpexProvider]:  # type: ignore[no-untyped-def]
    client = make_client(httpx.MockTransport(handler))
    return TwseProvider(client), TpexProvider(client)


def test_twse_daily_quotes() -> None:
    twse, _ = _providers()
    raw = twse.fetch_daily_prices(DAY, "twse")
    assert raw.params == {"date": "2026-10-16", "market": "twse"}
    bars = {b.symbol: b for b in twse.parse_daily_prices(raw)}
    assert set(bars) == {"0050", "2330", "020011"}
    tsmc = bars["2330"]
    assert (tsmc.open, tsmc.high, tsmc.low, tsmc.close) == (
        Decimal("2430.00"),
        Decimal("2445.00"),
        Decimal("2420.00"),
        Decimal("2420.00"),
    )
    assert tsmc.volume == 43_046_982
    assert tsmc.turnover == Decimal("104583063462")
    # No trade: prices are missing, not zero.
    assert (bars["020011"].close, bars["020011"].volume) == (None, 0)


def test_twse_no_data_day_is_empty() -> None:
    twse, _ = _providers()
    assert twse.parse_daily_prices(twse.fetch_daily_prices(date(2026, 10, 17), "twse")) == []


def test_twse_rejects_data_for_another_date() -> None:
    twse, _ = _providers()
    raw = RawResponse("mi_index", fixture("twse_mi_index_20261016.json"), {"date": "2026-10-15"})
    with pytest.raises(ValueError, match="asked for 2026-10-15"):
        twse.parse_daily_prices(raw)


def test_tpex_daily_quotes() -> None:
    _, tpex = _providers()
    bars = {b.symbol: b for b in tpex.parse_daily_prices(tpex.fetch_daily_prices(DAY, "tpex"))}
    assert set(bars) == {"006201", "6488", "2073"}
    assert bars["6488"].close == Decimal("902.00")
    assert bars["6488"].turnover == Decimal("13516821000")
    assert (bars["2073"].open, bars["2073"].volume) == (None, 0)


def test_tpex_empty_day() -> None:
    _, tpex = _providers()
    assert tpex.parse_daily_prices(tpex.fetch_daily_prices(date(2026, 10, 17), "tpex")) == []


def test_providers_refuse_other_markets() -> None:
    twse, tpex = _providers()
    with pytest.raises(PermanentProviderError):
        twse.fetch_daily_prices(DAY, "tpex")
    with pytest.raises(PermanentProviderError):
        tpex.fetch_daily_prices(DAY, "twse")


def test_twse_holiday_schedule() -> None:
    twse, _ = _providers()
    entries = {e.day: e for e in twse.parse_calendar(twse.fetch_calendar(2026))}
    assert not entries[date(2026, 10, 9)].is_trading_day  # 國慶日補假
    assert not entries[date(2026, 2, 12)].is_trading_day  # 市場無交易，僅辦理結算交割作業
    assert entries[date(2026, 2, 11)].is_trading_day  # 農曆春節前最後交易日
    assert entries[date(2026, 1, 2)].is_trading_day  # 國曆新年開始交易日
    assert twse.parse_calendar(twse.fetch_calendar(2010)) == []


def test_isin_master_lists() -> None:
    twse, _ = _providers()
    listed = {s.symbol: s for s in twse.parse_securities(twse.fetch_securities("twse"))}
    # Stocks, innovation board and ETFs only: no warrants, preferred, ETN, TDR or REITs.
    assert set(listed) == {"1101", "2330", "2237", "00400A", "0050"}
    assert listed["2330"].name == "台積電"
    assert listed["2330"].listed_date == date(1994, 9, 5)
    assert listed["2330"].industry == "半導體業"
    assert listed["0050"].type == "etf"
    assert listed["0050"].industry is None
    assert listed["2237"].type == "stock"

    otc = {s.symbol: s for s in twse.parse_securities(twse.fetch_securities("tpex"))}
    assert set(otc) == {"1240", "6488", "00411A", "006201"}
    assert {s.market for s in otc.values()} == {"tpex"}


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503), TransientProviderError),
        (httpx.Response(429), TransientProviderError),
        (httpx.Response(404), PermanentProviderError),
        (httpx.Response(200, text="<html>請求過於頻繁</html>"), TransientProviderError),
    ],
)
def test_http_failures_are_classified(response: httpx.Response, error: type[Exception]) -> None:
    twse, _ = _providers(lambda request: response)
    with pytest.raises(error):
        twse.fetch_daily_prices(DAY, "twse")


def test_network_errors_are_transient() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    twse, _ = _providers(boom)
    with pytest.raises(TransientProviderError, match="network error"):
        twse.fetch_calendar(2026)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.50", "1234.50"),
        ("--", None),
        ("----", None),
        ("", None),
        ("-21.00", "-21.00"),
        (None, None),
    ],
)
def test_clean_number(raw: str | None, expected: str | None) -> None:
    assert clean_number(raw) == expected
