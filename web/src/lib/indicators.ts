/**
 * Technical indicators, mirrored exactly by py/stockhub/engine/indicators.py (CLAUDE.md rule 11).
 *
 * Both evaluate the same expressions in the same order on doubles and are tested against
 * testdata/indicators.json. Change one, change the other, regenerate the fixture
 * (py/scripts/gen_indicator_fixture.py). Conventions are documented in the Python module:
 * inputs hold only traded bars (adjusted prices), outputs align with the input and are null
 * until enough history exists.
 */

export type Series = (number | null)[];

export function sma(values: readonly number[], n: number): Series {
  const out: Series = new Array(values.length).fill(null);
  for (let i = n - 1; i < values.length; i++) {
    let total = 0;
    for (let j = i - n + 1; j <= i; j++) total += values[j];
    out[i] = total / n;
  }
  return out;
}

export function ema(values: readonly number[], n: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length < n) return out;
  const alpha = 2 / (n + 1);
  let total = 0;
  for (let j = 0; j < n; j++) total += values[j];
  let prev = total / n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = alpha * values[i] + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

export type Macd = { dif: Series; signal: Series; histogram: Series };

export function macd(closes: readonly number[], fast = 12, slow = 26, signal = 9): Macd {
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const dif: Series = fastEma.map((f, i) => {
    const s = slowEma[i];
    return f !== null && s !== null ? f - s : null;
  });
  let start = dif.findIndex((v) => v !== null);
  if (start < 0) start = dif.length;
  const tail = ema(
    dif.slice(start).filter((v): v is number => v !== null),
    signal,
  );
  const sig: Series = [...new Array<null>(start).fill(null), ...tail];
  const histogram: Series = dif.map((d, i) => {
    const s = sig[i];
    return d !== null && s !== null ? d - s : null;
  });
  return { dif, signal: sig, histogram };
}

export type Kd = { k: Series; d: Series };

export function kd(
  highs: readonly number[],
  lows: readonly number[],
  closes: readonly number[],
  n = 9,
): Kd {
  const k: Series = new Array(closes.length).fill(null);
  const d: Series = new Array(closes.length).fill(null);
  let kPrev = 50;
  let dPrev = 50;
  for (let i = n - 1; i < closes.length; i++) {
    let hh = -Infinity;
    let ll = Infinity;
    for (let j = i - n + 1; j <= i; j++) {
      hh = Math.max(hh, highs[j]);
      ll = Math.min(lows[j], ll);
    }
    const rsv = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;
    kPrev = (2 * kPrev + rsv) / 3;
    dPrev = (2 * dPrev + kPrev) / 3;
    k[i] = kPrev;
    d[i] = dPrev;
  }
  return { k, d };
}

export function rsi(closes: readonly number[], n = 14): Series {
  const out: Series = new Array(closes.length).fill(null);
  if (closes.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const change = closes[i] - closes[i - 1];
    gain += Math.max(change, 0);
    loss += Math.max(-change, 0);
  }
  gain = gain / n;
  loss = loss / n;
  out[n] = rsiValue(gain, loss);
  for (let i = n + 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    gain = (gain * (n - 1) + Math.max(change, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-change, 0)) / n;
    out[i] = rsiValue(gain, loss);
  }
  return out;
}

function rsiValue(gain: number, loss: number): number {
  if (loss === 0) return gain === 0 ? 50 : 100;
  return 100 - 100 / (1 + gain / loss);
}
