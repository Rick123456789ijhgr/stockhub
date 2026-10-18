"""Technical indicators, mirrored exactly by web/src/lib/indicators.ts (CLAUDE.md rule 11).

Both implementations evaluate the same expressions in the same order on IEEE doubles, and
both are tested against testdata/indicators.json (generated from this module by
py/scripts/gen_indicator_fixture.py). Change one, change the other, regenerate the fixture.

Conventions (common Taiwanese charting defaults):
- Input series contain only bars that traded (no None closes); feed adjusted prices.
- Outputs align with the input; None until enough history exists.
- SMA sums each window directly (no running sum, so no drift).
- EMA is seeded with the SMA of its first n values, then e = a*v + (1-a)*e_prev, a = 2/(n+1).
- MACD(12, 26, 9): DIF = EMA12 - EMA26, signal = EMA9 of DIF, histogram = DIF - signal.
- KD(9): RSV = (C - L9) / (H9 - L9) * 100 (50 when H9 == L9); K = (2*K_prev + RSV) / 3,
  D = (2*D_prev + K) / 3, both starting from 50.
- RSI(14), Wilder: first averages are plain means of the first n changes, then
  avg = (avg*(n-1) + x) / n; RSI = 100 - 100 / (1 + gain/loss), 100 when loss = 0
  (50 when both are 0).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Series = list[float | None]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        total = 0.0
        for v in values[i - n + 1 : i + 1]:
            total += v
        out[i] = total / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2 / (n + 1)
    total = 0.0
    for v in values[:n]:
        total += v
    prev = total / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


@dataclass(frozen=True)
class Macd:
    dif: Series
    signal: Series
    histogram: Series


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Macd:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    dif: Series = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    start = next((i for i, v in enumerate(dif) if v is not None), len(dif))
    tail = ema([v for v in dif[start:] if v is not None], signal)
    sig: Series = [None] * start
    sig.extend(tail)
    hist: Series = [
        d - s if d is not None and s is not None else None for d, s in zip(dif, sig, strict=True)
    ]
    return Macd(dif, sig, hist)


@dataclass(frozen=True)
class Kd:
    k: Series
    d: Series


def kd(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 9) -> Kd:
    k_out: Series = [None] * len(closes)
    d_out: Series = [None] * len(closes)
    k_prev = d_prev = 50.0
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1 : i + 1])
        ll = min(lows[i - n + 1 : i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k_prev = (2 * k_prev + rsv) / 3
        d_prev = (2 * d_prev + k_prev) / 3
        k_out[i], d_out[i] = k_prev, d_prev
    return Kd(k_out, d_out)


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    gain = loss = 0.0
    for i in range(1, n + 1):
        change = closes[i] - closes[i - 1]
        gain += max(change, 0.0)
        loss += max(-change, 0.0)
    gain, loss = gain / n, loss / n
    out[n] = _rsi_value(gain, loss)
    for i in range(n + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = (gain * (n - 1) + max(change, 0.0)) / n
        loss = (loss * (n - 1) + max(-change, 0.0)) / n
        out[i] = _rsi_value(gain, loss)
    return out


def _rsi_value(gain: float, loss: float) -> float:
    if loss == 0:
        return 50.0 if gain == 0 else 100.0
    return 100 - 100 / (1 + gain / loss)
