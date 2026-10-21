"""Chip tables (籌碼) of TWSE, TPEx and TDCC: parsing of every recorded layout, and checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from stockhub.etl.providers.base import (
    DistributionLevel,
    ForeignHolding,
    InstitutionalTrade,
    MarginBalance,
    PermanentProviderError,
    RawResponse,
)
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.tdcc import TdccProvider
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider
from stockhub.etl.quality import (
    check_distribution,
    check_foreign_holding,
    check_institutional_trade,
    check_margin_balance,
)

from .official_sources import fixture, official_handler

DAY = date(2026, 10, 16)
HOLIDAY = date(2026, 10, 17)


def _providers() -> tuple[TwseProvider, TpexProvider, TdccProvider]:
    client = make_client(httpx.MockTransport(official_handler))
    return TwseProvider(client), TpexProvider(client), TdccProvider(client)


def _by_symbol[T: (InstitutionalTrade, ForeignHolding, MarginBalance)](
    items: list[T],
) -> dict[str, T]:
    return {i.symbol: i for i in items}


# ----------------------------------------------------------------------------- institutional


def test_twse_t86_current_layout() -> None:
    twse, _, _ = _providers()
    raw = twse.fetch_institutional_trades(DAY, "twse")
    assert raw.params == {"date": "2026-10-16", "market": "twse"}
    trades = _by_symbol(twse.parse_institutional_trades(raw))
    tsmc = trades["2330"]
    assert (tsmc.foreign_buy, tsmc.foreign_sell, tsmc.foreign_net) == (
        11_295_871,
        33_342_013,
        -22_046_142,
    )
    assert tsmc.foreign_dealer_net == 0
    assert (tsmc.trust_net, tsmc.dealer_net, tsmc.total_net) == (710_240, -1_035_928, -22_371_830)
    # Dealer buys and sells are own account + hedging.
    assert (tsmc.dealer_buy, tsmc.dealer_self_net, tsmc.dealer_hedge_net) == (
        924_365,
        -1_012_493,
        -23_435,
    )
    assert all(check_institutional_trade(t) == [] for t in trades.values())


def test_twse_t86_2012_layout_leaves_unsplit_groups_empty() -> None:
    twse, _, _ = _providers()
    trades = _by_symbol(
        twse.parse_institutional_trades(twse.fetch_institutional_trades(date(2012, 5, 2), "twse"))
    )
    umc = trades["2303"]
    assert (umc.foreign_net, umc.trust_net, umc.dealer_net, umc.total_net) == (
        18_411_238,
        5_707_000,
        646_000,
        24_764_238,
    )
    assert (umc.dealer_buy, umc.dealer_sell) == (648_000, 2_000)
    assert umc.foreign_dealer_net is None
    assert umc.dealer_self_net is None
    assert check_institutional_trade(umc) == []


def test_twse_t86_2015_layout_splits_dealers_only() -> None:
    twse, _, _ = _providers()
    trades = _by_symbol(
        twse.parse_institutional_trades(twse.fetch_institutional_trades(date(2015, 6, 1), "twse"))
    )
    mitac = trades["3706"]
    assert (mitac.dealer_self_net, mitac.dealer_hedge_net, mitac.dealer_net) == (
        86_000,
        4_908_000,
        4_994_000,
    )
    assert mitac.foreign_dealer_net is None
    assert check_institutional_trade(mitac) == []


def test_tpex_institutional_layouts() -> None:
    _, tpex, _ = _providers()
    now = _by_symbol(tpex.parse_institutional_trades(tpex.fetch_institutional_trades(DAY, "tpex")))
    gw = now["6488"]
    assert (gw.foreign_net, gw.trust_net, gw.dealer_net, gw.total_net) == (
        -4_456_672,
        221_714,
        -147_433,
        -4_382_391,
    )
    assert (gw.dealer_self_net, gw.dealer_hedge_net, gw.foreign_dealer_net) == (-96_740, -50_693, 0)
    old = _by_symbol(
        tpex.parse_institutional_trades(tpex.fetch_institutional_trades(date(2015, 6, 1), "tpex"))
    )
    assert (old["1264"].dealer_buy, old["1264"].dealer_sell, old["1264"].dealer_self_net) == (
        5_000,
        1_000,
        4_000,
    )
    assert old["1264"].foreign_dealer_net is None
    assert all(check_institutional_trade(t) == [] for t in [*now.values(), *old.values()])


def test_holidays_parse_empty() -> None:
    twse, tpex, _ = _providers()
    assert twse.parse_institutional_trades(twse.fetch_institutional_trades(HOLIDAY, "twse")) == []
    assert tpex.parse_institutional_trades(tpex.fetch_institutional_trades(HOLIDAY, "tpex")) == []
    assert twse.parse_margin(twse.fetch_margin(HOLIDAY, "twse")) == []
    assert tpex.parse_margin(tpex.fetch_margin(HOLIDAY, "tpex")) == []
    assert twse.parse_foreign_holdings(twse.fetch_foreign_holdings(HOLIDAY, "twse")) == []
    assert tpex.parse_market_institutional(tpex.fetch_market_institutional(HOLIDAY, "tpex")) == []


def test_recorded_holiday_tables_parse_empty() -> None:
    twse, tpex, _ = _providers()
    params = {"date": "2026-10-17", "market": "twse"}
    assert (
        twse.parse_institutional_trades(RawResponse("t86", fixture("twse_t86_nodata.json"), params))
        == []
    )
    assert twse.parse_margin(RawResponse("m", fixture("twse_mi_margn_nodata.json"), params)) == []
    tpex_raw = RawResponse("i", fixture("tpex_insti_nodata.json"), {**params, "market": "tpex"})
    assert tpex.parse_institutional_trades(tpex_raw) == []


def test_data_for_another_date_is_rejected() -> None:
    twse, tpex, _ = _providers()
    params = {"date": "2026-10-15", "market": "twse"}
    with pytest.raises(ValueError, match="asked for 2026-10-15"):
        twse.parse_institutional_trades(
            RawResponse("t86", fixture("twse_t86_20261016.json"), params)
        )
    with pytest.raises(ValueError, match="asked for 2026-10-15"):
        tpex.parse_margin(RawResponse("m", fixture("tpex_margin_20261016.json"), params))


def test_wrong_market_is_permanent() -> None:
    twse, tpex, _ = _providers()
    with pytest.raises(PermanentProviderError):
        twse.fetch_margin(DAY, "tpex")
    with pytest.raises(PermanentProviderError):
        tpex.fetch_institutional_trades(DAY, "twse")


# ----------------------------------------------------------------------------- margin


def test_twse_margin_in_shares_with_market_total() -> None:
    twse, _, _ = _providers()
    (table,) = twse.parse_margin(twse.fetch_margin(DAY, "twse"))
    tsmc = _by_symbol(table.rows)["2330"]
    assert (tsmc.margin_buy, tsmc.margin_sell, tsmc.margin_redeem) == (
        1_157_000,
        1_160_000,
        110_000,
    )
    assert (tsmc.margin_prev, tsmc.margin_balance, tsmc.margin_limit) == (
        34_223_000,
        34_110_000,
        6_483_092_000,
    )
    # 融券: the table lists 買進 (cover) before 賣出 (short sale).
    assert (tsmc.short_sell, tsmc.short_cover, tsmc.short_balance) == (4_000, 3_000, 9_000)
    assert tsmc.offset_shares == 2_000
    assert table.total is not None
    assert table.total.margin_balance == 9_538_664_000
    assert table.total.margin_balance_amount == Decimal("645594048000")
    assert all(check_margin_balance(r) == [] for r in table.rows)


def test_tpex_margin_in_shares_with_market_total() -> None:
    _, tpex, _ = _providers()
    (table,) = tpex.parse_margin(tpex.fetch_margin(DAY, "tpex"))
    gw = _by_symbol(table.rows)["6488"]
    assert (gw.margin_prev, gw.margin_buy, gw.margin_sell, gw.margin_balance) == (
        13_977_000,
        1_009_000,
        1_014_000,
        13_969_000,
    )
    assert (gw.short_sell, gw.short_cover, gw.short_balance) == (9_000, 22_000, 272_000)
    assert table.total is not None
    assert (table.total.margin_balance, table.total.short_balance) == (2_364_632_000, 38_246_000)
    assert table.total.margin_balance_amount == Decimal("218250119000")
    assert all(check_margin_balance(r) == [] for r in table.rows)


def test_margin_continuity_check() -> None:
    twse, _, _ = _providers()
    (table,) = twse.parse_margin(twse.fetch_margin(DAY, "twse"))
    tsmc = _by_symbol(table.rows)["2330"]
    broken = tsmc.model_copy(update={"margin_balance": tsmc.margin_balance + 1000})
    assert check_margin_balance(broken) == ["margin_balance_mismatch"]
    broken = tsmc.model_copy(update={"short_cover": 0})
    assert check_margin_balance(broken) == ["short_balance_mismatch"]


# ----------------------------------------------------------------------------- holdings


def test_foreign_holdings_both_markets() -> None:
    twse, tpex, _ = _providers()
    listed = _by_symbol(twse.parse_foreign_holdings(twse.fetch_foreign_holdings(DAY, "twse")))
    assert listed["2330"].foreign_shares == 17_827_007_932
    assert listed["2330"].foreign_ratio == Decimal("0.6874")
    assert listed["2330"].limit_ratio == Decimal("1")
    old = _by_symbol(
        twse.parse_foreign_holdings(twse.fetch_foreign_holdings(date(2012, 5, 2), "twse"))
    )
    assert old["2330"].foreign_ratio == Decimal("0.7716")
    otc = _by_symbol(tpex.parse_foreign_holdings(tpex.fetch_foreign_holdings(DAY, "tpex")))
    assert (otc["6488"].issued_shares, otc["6488"].foreign_ratio) == (
        528_113_725,
        Decimal("0.3113"),
    )
    rows = [*listed.values(), *old.values(), *otc.values()]
    assert all(check_foreign_holding(r) == [] for r in rows)
    bad = listed["2330"].model_copy(update={"foreign_ratio": Decimal("68.74")})
    assert check_foreign_holding(bad) == ["ratio_out_of_range", "ratio_mismatch"]


# ----------------------------------------------------------------------------- market totals


def test_market_institutional_layouts() -> None:
    twse, tpex, _ = _providers()
    now = {
        r.investor: r
        for r in twse.parse_market_institutional(twse.fetch_market_institutional(DAY, "twse"))
    }
    # Dealers appear as their two parts; the total row is added from them.
    assert (
        now["dealer"].net_amount == now["dealer_self"].net_amount + now["dealer_hedge"].net_amount
    )
    assert now["foreign"].net_amount == Decimal(-46_147_162_837)
    assert now["total"].net_amount == Decimal(-68_513_664_272)
    old = {
        r.investor: r
        for r in twse.parse_market_institutional(
            twse.fetch_market_institutional(date(2012, 5, 2), "twse")
        )
    }
    assert set(old) == {"dealer", "trust", "foreign", "total"}
    otc = {
        r.investor: r
        for r in tpex.parse_market_institutional(tpex.fetch_market_institutional(DAY, "tpex"))
    }
    assert otc["foreign"].net_amount == Decimal(-3_284_333_001)
    assert otc["dealer"].net_amount == Decimal(-3_280_531_642)
    assert otc["total"].net_amount == Decimal(-5_190_759_111)


# ----------------------------------------------------------------------------- TDCC


def test_tdcc_distribution() -> None:
    _, _, tdcc = _providers()
    levels = tdcc.parse_shareholding_distribution(tdcc.fetch_shareholding_distribution())
    # Bonds such as 000218 are out of scope.
    assert {lv.symbol for lv in levels} == {"2330", "0050", "6488"}
    tsmc = {lv.level: lv for lv in levels if lv.symbol == "2330"}
    assert len(tsmc) == 17
    assert tsmc[15].week_date == DAY
    assert (tsmc[15].holders, tsmc[15].shares, tsmc[15].ratio) == (
        1476,
        21_928_634_563,
        Decimal("0.8456"),
    )
    for symbol in ("2330", "0050", "6488"):
        assert check_distribution([lv for lv in levels if lv.symbol == symbol]) == []


def test_tdcc_check_uses_adjustment_either_way() -> None:
    def level(n: int, shares: int) -> DistributionLevel:
        return DistributionLevel(
            symbol="2330", week_date=DAY, level=n, holders=1, shares=shares, ratio=Decimal(0)
        )

    # 0050 publishes total = brackets - adjustment, 2330 brackets + adjustment.
    assert check_distribution([level(1, 100), level(16, 10), level(17, 90)]) == []
    assert check_distribution([level(1, 100), level(16, 10), level(17, 110)]) == []
    assert check_distribution([level(1, 100), level(17, 95)]) == ["levels_do_not_add_up"]
    assert check_distribution([level(1, 100)]) == ["missing_total"]


def test_tdcc_rejects_unknown_header() -> None:
    _, _, tdcc = _providers()
    with pytest.raises(ValueError, match="header"):
        tdcc.parse_shareholding_distribution(RawResponse("d", "a,b,c\n1,2,3\n", {}))
