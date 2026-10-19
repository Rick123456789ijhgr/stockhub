/**
 * Portfolio math: a line-by-line port of py/stockhub/engine/portfolio.py (CLAUDE.md rule
 * 11). Both evaluate the same expressions in the same order on IEEE doubles and are tested
 * against testdata/portfolio.json; change one, change the other, regenerate the fixture
 * (py/scripts/gen_portfolio_fixture.py). The conventions are documented in the Python
 * module. Safe for client components (the transaction form fills fees and tax with it).
 */

export const EPS = 1e-6;

export type Rounding = "floor" | "round";
export type DiscountMode = "instant" | "rebate";

/** Whole TWD: floor (元以下捨去) or half-up rounding, robust to float noise. */
export function roundMoney(value: number, rounding: Rounding = "floor"): number {
  if (rounding === "round") return Math.floor(value + 0.5 + EPS);
  return Math.floor(value + EPS);
}

/** Half-up rounding to `digits` decimals (same result as the Python reference). */
export function roundTo(value: number, digits: number): number {
  const scale = 10 ** digits;
  return Math.floor(value * scale + 0.5) / scale;
}

// --- fees and tax ---------------------------------------------------------------------

export type FeeSettings = {
  rate: number;
  /** Multiplier: 0.28 = 2.8 折, 1 = none. */
  discount: number;
  minFee: number;
  /** Minimum for orders of fewer than 1,000 shares. */
  minFeeOddLot: number;
  discountMode: DiscountMode;
  rounding: Rounding;
};

export const DEFAULT_FEES: FeeSettings = {
  rate: 0.001425,
  discount: 1,
  minFee: 20,
  minFeeOddLot: 1,
  discountMode: "instant",
  rounding: "floor",
};

export type Fee = { fee: number; rebate: number };

/**
 * Fee for a trade worth `amount`. Instant: the discounted fee is charged. Rebate: the full
 * fee is charged and the difference to the discounted fee comes back later.
 */
export function brokerFee(amount: number, quantity: number, s: FeeSettings): Fee {
  const minimum = quantity < 1000 ? s.minFeeOddLot : s.minFee;
  const base = amount * s.rate;
  const full = Math.max(minimum, roundMoney(base, s.rounding));
  const discounted = Math.max(minimum, roundMoney(base * s.discount, s.rounding));
  if (s.discountMode === "instant") return { fee: discounted, rebate: 0 };
  return { fee: full, rebate: Math.max(0, full - discounted) };
}

/** What a trade finally costs in fees (after any rebate). */
export function netFee(amount: number, quantity: number, s: FeeSettings): number {
  const f = brokerFee(amount, quantity, s);
  return f.fee - f.rebate;
}

export const BOND_ETF_EXEMPT = ["2017-01-01", "2026-12-31"] as const;
export const DAY_TRADE_HALF = ["2017-04-28", "2027-12-31"] as const;

/**
 * Securities transaction tax on sells: stocks 0.3% (day trades 0.15% while the cut runs),
 * ETFs 0.1%, bond ETFs (symbol ending in B) exempt while the exemption runs.
 */
export function taxRate(
  securityType: string,
  symbol: string,
  tradeDate: string,
  dayTrade: boolean,
): number {
  if (securityType === "etf") {
    const exempt = BOND_ETF_EXEMPT[0] <= tradeDate && tradeDate <= BOND_ETF_EXEMPT[1];
    if (symbol.endsWith("B") && exempt) return 0;
    return 0.001;
  }
  if (dayTrade && DAY_TRADE_HALF[0] <= tradeDate && tradeDate <= DAY_TRADE_HALF[1]) {
    return 0.0015;
  }
  return 0.003;
}

export function transactionTax(amount: number, rate: number): number {
  return roundMoney(amount * rate);
}

// --- ledger replay --------------------------------------------------------------------

export type Trade = {
  id: string;
  stock: string;
  date: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  rebate: number;
};

/** A corporate_actions row (TWD per share; ratios as stored). */
export type Action = {
  stock: string;
  exDate: string;
  actionType: string;
  cashDividend: number | null;
  stockDividendRatio: number | null;
  ratio: number | null;
  prevClose: number | null;
  referencePrice: number | null;
};

/**
 * Latest price of a stock: an intraday quote or the last daily close. `prevClose` is on
 * the same share basis (the exchange reference price on an ex-date).
 */
export type Mark = { date: string; price: number; prevClose: number | null };

export type Security = { type: string; symbol: string };

export type Entitlement = {
  cashPerShare: number;
  /** New shares per share held (stock dividends). */
  stockRatio: number;
  /** Shares after / before (splits, reductions); 1 for dividends. */
  shareRatio: number;
  /** A ratio was inferred from the exchange's reference price. */
  implied: boolean;
};

const DIVIDEND_TYPES = ["cash_dividend", "stock_dividend", "cash_and_stock_dividend"];
const SHARE_TYPES = ["split", "reverse_split", "capital_reduction"];

/**
 * What one share before the ex-date turns into; null for events with no automatic effect
 * on a holder. Missing ratios are inferred from the reference price (see Python).
 */
export function entitlement(a: Action): Entitlement | null {
  const prev = a.prevClose || 0;
  const ref = a.referencePrice || 0;
  const usable = prev > 0 && ref > 0;
  const cash = a.cashDividend !== null ? a.cashDividend : 0;
  if (DIVIDEND_TYPES.includes(a.actionType)) {
    if (a.stockDividendRatio !== null) {
      return { cashPerShare: cash, stockRatio: a.stockDividendRatio, shareRatio: 1, implied: false };
    }
    if (a.actionType === "cash_dividend" || !usable) {
      return { cashPerShare: cash, stockRatio: 0, shareRatio: 1, implied: false };
    }
    const implied = roundTo((prev - cash) / ref - 1, 3);
    return { cashPerShare: cash, stockRatio: Math.max(0, implied), shareRatio: 1, implied: true };
  }
  if (SHARE_TYPES.includes(a.actionType)) {
    if (a.ratio !== null) {
      return { cashPerShare: cash, stockRatio: 0, shareRatio: a.ratio, implied: false };
    }
    if (!usable) return null;
    return {
      cashPerShare: cash,
      stockRatio: 0,
      shareRatio: roundTo((prev - cash) / ref, 3),
      implied: true,
    };
  }
  return null;
}

export type DividendEntry = {
  stock: string;
  exDate: string;
  actionType: string;
  sharesHeld: number;
  cashPerShare: number;
  cash: number;
  stockRatio: number;
  stockShares: number;
  shareRatio: number;
  sharesAfter: number;
  implied: boolean;
};

export type RealizedEntry = {
  id: string;
  stock: string;
  date: string;
  quantity: number;
  proceeds: number;
  cost: number;
  fee: number;
  tax: number;
  pnl: number;
};

/** A sell larger than the holding at that point; left out of the replay. */
export type Issue = { id: string; stock: string; date: string; held: number; quantity: number };

export type Position = {
  stock: string;
  shares: number;
  cost: number;
  realized: number;
  dividends: number;
  rebates: number;
  avgCost: number | null;
  markDate: string | null;
  price: number | null;
  marketValue: number | null;
  estSellCost: number | null;
  unrealized: number | null;
  dayChange: number | null;
};

export type Ledger = {
  positions: Position[];
  realized: RealizedEntry[];
  dividends: DividendEntry[];
  issues: Issue[];
};

type Day = { actions: Action[]; buys: Trade[]; sells: Trade[] };

function dayOf(days: Map<string, Day>, date: string): Day {
  let day = days.get(date);
  if (!day) {
    day = { actions: [], buys: [], sells: [] };
    days.set(date, day);
  }
  return day;
}

const byKey = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/**
 * Replay trades (in id order) and corporate actions up to `asOf`, then value the open
 * positions at `marks`. Positions are sorted by stock key; actions on stocks that were
 * never traded are ignored.
 */
export function replay(
  trades: readonly Trade[],
  actions: readonly Action[],
  opts: {
    asOf: string;
    marks?: Record<string, Mark>;
    securities?: Record<string, Security>;
    fees?: FeeSettings;
  },
): Ledger {
  const marks = opts.marks ?? {};
  const securities = opts.securities ?? {};
  const feeSettings = opts.fees ?? DEFAULT_FEES;
  const stocks = new Map<string, Map<string, Day>>();
  for (const t of trades) {
    if (!stocks.has(t.stock)) stocks.set(t.stock, new Map());
    const day = dayOf(stocks.get(t.stock)!, t.date);
    (t.side === "buy" ? day.buys : day.sells).push(t);
  }
  for (const a of actions) {
    const days = stocks.get(a.stock);
    if (days && a.exDate <= opts.asOf) dayOf(days, a.exDate).actions.push(a);
  }

  const out: Ledger = { positions: [], realized: [], dividends: [], issues: [] };
  for (const stock of [...stocks.keys()].sort(byKey)) {
    const days = stocks.get(stock)!;
    const p: Position = {
      stock,
      shares: 0,
      cost: 0,
      realized: 0,
      dividends: 0,
      rebates: 0,
      avgCost: null,
      markDate: null,
      price: null,
      marketValue: null,
      estSellCost: null,
      unrealized: null,
      dayChange: null,
    };
    const mark = marks[stock] ?? null;
    let base: number | null = null;
    let markBuys = 0;
    let markSells = 0;
    let stale = false;
    for (const date of [...days.keys()].sort(byKey)) {
      const day = days.get(date)!;
      if (mark !== null && date > mark.date) {
        if (base === null) base = p.shares;
        stale = true;
      }
      for (const a of day.actions) applyAction(p, a, out);
      if (mark !== null && date === mark.date) base = p.shares;
      for (const t of day.buys) {
        p.shares += t.quantity;
        p.cost += t.quantity * t.price + t.fee;
        p.rebates += t.rebate;
        if (mark !== null && date === mark.date) markBuys += t.quantity * t.price;
      }
      for (const t of day.sells) {
        if (t.quantity > p.shares) {
          out.issues.push({ id: t.id, stock, date, held: p.shares, quantity: t.quantity });
          continue;
        }
        const costOut = t.quantity === p.shares ? p.cost : (p.cost * t.quantity) / p.shares;
        const proceeds = t.quantity * t.price;
        const pnl = proceeds - t.fee - t.tax - costOut;
        out.realized.push({
          id: t.id,
          stock,
          date,
          quantity: t.quantity,
          proceeds,
          cost: costOut,
          fee: t.fee,
          tax: t.tax,
          pnl,
        });
        p.realized += pnl;
        p.rebates += t.rebate;
        p.shares -= t.quantity;
        p.cost = p.shares === 0 ? 0 : p.cost - costOut;
        if (mark !== null && date === mark.date) markSells += proceeds;
      }
    }
    if (base === null) base = p.shares;
    value(p, mark, securities[stock] ?? null, feeSettings, opts.asOf);
    const moved = p.shares > 0 || base > 0;
    if (mark !== null && mark.prevClose !== null && !stale && moved) {
      p.dayChange = p.shares * mark.price - base * mark.prevClose - markBuys + markSells;
    }
    out.positions.push(p);
  }
  return out;
}

function applyAction(p: Position, a: Action, out: Ledger): void {
  const held = p.shares;
  if (held <= 0) return;
  const e = entitlement(a);
  if (e === null) return;
  const cash = roundMoney(held * e.cashPerShare);
  const stockShares = roundMoney(held * e.stockRatio);
  const after = e.shareRatio === 1 ? held : roundMoney(held * e.shareRatio);
  p.shares = after + stockShares;
  p.dividends += cash;
  if (p.shares === 0) {
    p.realized -= p.cost;
    p.cost = 0;
  }
  out.dividends.push({
    stock: p.stock,
    exDate: a.exDate,
    actionType: a.actionType,
    sharesHeld: held,
    cashPerShare: e.cashPerShare,
    cash,
    stockRatio: e.stockRatio,
    stockShares,
    shareRatio: e.shareRatio,
    sharesAfter: p.shares,
    implied: e.implied,
  });
}

function value(
  p: Position,
  mark: Mark | null,
  sec: Security | null,
  fees: FeeSettings,
  asOf: string,
): void {
  if (p.shares > 0) p.avgCost = p.cost / p.shares;
  if (mark === null) return;
  p.markDate = mark.date;
  p.price = mark.price;
  if (p.shares <= 0) return;
  const v = p.shares * mark.price;
  const rate = sec ? taxRate(sec.type, sec.symbol, asOf, false) : 0.003;
  const est = netFee(v, p.shares, fees) + transactionTax(v, rate);
  p.marketValue = v;
  p.estSellCost = est;
  p.unrealized = v - p.cost - est;
}

export type Totals = {
  cost: number;
  marketValue: number;
  unrealized: number;
  realized: number;
  dividends: number;
  rebates: number;
  dayChange: number;
};

/** Sums over positions; open positions without a mark add only their cost. */
export function totals(positions: readonly Position[]): Totals {
  const t: Totals = {
    cost: 0,
    marketValue: 0,
    unrealized: 0,
    realized: 0,
    dividends: 0,
    rebates: 0,
    dayChange: 0,
  };
  for (const p of positions) {
    t.cost += p.cost;
    t.marketValue += p.marketValue ?? 0;
    t.unrealized += p.unrealized ?? 0;
    t.realized += p.realized;
    t.dividends += p.dividends;
    t.rebates += p.rebates;
    t.dayChange += p.dayChange ?? 0;
  }
  return t;
}
