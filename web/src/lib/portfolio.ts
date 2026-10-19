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
  dayTrade: boolean;
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

/** What actually arrived for one event (null = keep the estimate for that part). */
export type Receipt = { cash: number | null; shares: number | null };

export function receiptKey(stock: string, exDate: string, actionType: string): string {
  return `${stock}|${exDate}|${actionType}`;
}

/** An announced, not yet official event (除權除息預告); cash null = not announced. */
export type Preview = {
  stock: string;
  exDate: string;
  actionType: string;
  cashDividend: number | null;
  stockDividendRatio: number | null;
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

/** (since, rate, threshold): 二代健保補充保費 on dividends. */
export const NHI_RATES = [
  ["2021-01-01", 0.0211, 20_000],
  ["2016-01-01", 0.0191, 20_000],
  ["2013-01-01", 0.02, 5_000],
] as const;
const NHI_CAP = 10_000_000;
const PAR_VALUE = 10;

/**
 * 二代健保補充保費 on one dividend payment: cash plus stock dividends at par, when the
 * payment reaches the year's threshold (capped at 10 million); 0 before 2013.
 */
export function nhiPremium(cash: number, stockShares: number, exDate: string): number {
  for (const [since, rate, threshold] of NHI_RATES) {
    if (exDate >= since) {
      const base = cash + stockShares * PAR_VALUE;
      if (base < threshold) return 0;
      return roundMoney(Math.min(base, NHI_CAP) * rate, "round");
    }
  }
  return 0;
}

export type DividendEntry = {
  stock: string;
  exDate: string;
  actionType: string;
  sharesHeld: number;
  cashPerShare: number;
  /** Received when `received`, else the estimate. */
  cash: number;
  stockRatio: number;
  stockShares: number;
  shareRatio: number;
  sharesAfter: number;
  implied: boolean;
  estCash: number;
  estStockShares: number;
  /** Estimated premium on the estimate; 0 once received (already net). */
  nhi: number;
  received: boolean;
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
  dayTrade: boolean;
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
 * Actions plus previews whose ex-date has come (up to `asOf`) but which the official table
 * does not carry yet, so today's dividend counts before the evening import.
 */
export function withPreviews(
  actions: readonly Action[],
  previews: readonly Preview[],
  asOf: string,
): Action[] {
  const known = new Set(actions.map((a) => `${a.stock}|${a.exDate}`));
  const extra = previews
    .filter((v) => v.exDate <= asOf && !known.has(`${v.stock}|${v.exDate}`))
    .map(
      (v): Action => ({
        stock: v.stock,
        exDate: v.exDate,
        actionType: v.actionType,
        cashDividend: v.cashDividend,
        stockDividendRatio: v.stockDividendRatio,
        ratio: null,
        prevClose: null,
        referencePrice: null,
      }),
    );
  return [...actions, ...extra];
}

/** `total` (a fee or tax) pro rata for `part` of `whole` shares; exact when whole. */
function part(total: number, p: number, whole: number): number {
  return p === whole ? total : (total * p) / whole;
}

/**
 * Replay trades (in id order) and corporate actions up to `asOf`, then value the open
 * positions at `marks`. Positions are sorted by stock key; actions on stocks that were
 * never traded are ignored. Day trades settle on their own (see the Python module).
 */
export function replay(
  trades: readonly Trade[],
  actions: readonly Action[],
  opts: {
    asOf: string;
    marks?: Record<string, Mark>;
    securities?: Record<string, Security>;
    fees?: FeeSettings;
    receipts?: Record<string, Receipt>;
  },
): Ledger {
  const marks = opts.marks ?? {};
  const securities = opts.securities ?? {};
  const feeSettings = opts.fees ?? DEFAULT_FEES;
  const received = opts.receipts ?? {};
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
      const onMark = mark !== null && date === mark.date;
      if (mark !== null && date > mark.date) {
        if (base === null) base = p.shares;
        stale = true;
      }
      for (const a of day.actions) applyAction(p, a, out, received);
      if (onMark) base = p.shares;
      let dtBuy = 0;
      for (const t of day.buys) if (t.dayTrade) dtBuy += t.quantity;
      let dtSell = 0;
      for (const t of day.sells) if (t.dayTrade) dtSell += t.quantity;
      const matched = Math.min(dtBuy, dtSell);
      let buyLeft = matched;
      let dtCost = 0;
      for (const t of day.buys) {
        const m = t.dayTrade ? Math.min(t.quantity, buyLeft) : 0;
        buyLeft -= m;
        const rest = t.quantity - m;
        if (m > 0) dtCost += m * t.price + part(t.fee, m, t.quantity);
        if (rest > 0) {
          p.shares += rest;
          p.cost += rest * t.price + part(t.fee, rest, t.quantity);
        }
        p.rebates += t.rebate;
        if (onMark) markBuys += t.quantity * t.price;
      }
      let sellLeft = matched;
      for (const t of day.sells) {
        const m = t.dayTrade ? Math.min(t.quantity, sellLeft) : 0;
        sellLeft -= m;
        const rest = t.quantity - m;
        const feeM = m > 0 ? part(t.fee, m, t.quantity) : 0;
        const taxM = m > 0 ? part(t.tax, m, t.quantity) : 0;
        if (m > 0) {
          const costM = sellLeft === 0 ? dtCost : (dtCost * m) / (sellLeft + m);
          dtCost -= costM;
          const proceedsM = m * t.price;
          const pnlM = proceedsM - feeM - taxM - costM;
          out.realized.push({
            id: t.id,
            stock,
            date,
            quantity: m,
            proceeds: proceedsM,
            cost: costM,
            fee: feeM,
            tax: taxM,
            pnl: pnlM,
            dayTrade: true,
          });
          p.realized += pnlM;
          if (onMark) markSells += proceedsM;
        }
        p.rebates += t.rebate;
        if (rest === 0) continue;
        if (rest > p.shares) {
          out.issues.push({ id: t.id, stock, date, held: p.shares, quantity: rest });
          continue;
        }
        const feeR = t.fee - feeM;
        const taxR = t.tax - taxM;
        const costOut = rest === p.shares ? p.cost : (p.cost * rest) / p.shares;
        const proceeds = rest * t.price;
        const pnl = proceeds - feeR - taxR - costOut;
        out.realized.push({
          id: t.id,
          stock,
          date,
          quantity: rest,
          proceeds,
          cost: costOut,
          fee: feeR,
          tax: taxR,
          pnl,
          dayTrade: false,
        });
        p.realized += pnl;
        p.shares -= rest;
        p.cost = p.shares === 0 ? 0 : p.cost - costOut;
        if (onMark) markSells += proceeds;
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

function applyAction(
  p: Position,
  a: Action,
  out: Ledger,
  receipts: Record<string, Receipt>,
): void {
  const held = p.shares;
  if (held <= 0) return;
  const e = entitlement(a);
  if (e === null) return;
  const estCash = roundMoney(held * e.cashPerShare);
  const estShares = roundMoney(held * e.stockRatio);
  const r = receipts[receiptKey(p.stock, a.exDate, a.actionType)] ?? null;
  const cash = r === null || r.cash === null ? estCash : r.cash;
  const stockShares = r === null || r.shares === null ? estShares : r.shares;
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
    estCash,
    estStockShares: estShares,
    nhi: r !== null ? 0 : nhiPremium(estCash, estShares, a.exDate),
    received: r !== null,
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

export type UpcomingEntry = {
  stock: string;
  exDate: string;
  actionType: string;
  shares: number;
  cashPerShare: number | null;
  /** Null while the amount is not announced. */
  cash: number | null;
  stockRatio: number;
  stockShares: number;
  nhi: number | null;
};

/**
 * Announced events after `asOf` on open positions, assuming the holding stays as it is
 * until the day before the ex-date. Sorted by ex-date, then stock.
 */
export function upcoming(
  positions: readonly Position[],
  previews: readonly Preview[],
  asOf: string,
): UpcomingEntry[] {
  const held = new Map(positions.filter((p) => p.shares > 0).map((p) => [p.stock, p.shares]));
  const out: UpcomingEntry[] = [];
  const sorted = [...previews].sort((a, b) => byKey(a.exDate, b.exDate) || byKey(a.stock, b.stock));
  for (const v of sorted) {
    const shares = held.get(v.stock) ?? 0;
    if (v.exDate <= asOf || shares <= 0) continue;
    const ratio = v.stockDividendRatio || 0;
    const stockShares = roundMoney(shares * ratio);
    const cash = v.cashDividend === null ? null : roundMoney(shares * v.cashDividend);
    const nhi = cash === null ? null : nhiPremium(cash, stockShares, v.exDate);
    out.push({
      stock: v.stock,
      exDate: v.exDate,
      actionType: v.actionType,
      shares,
      cashPerShare: v.cashDividend,
      cash,
      stockRatio: ratio,
      stockShares,
      nhi,
    });
  }
  return out;
}
