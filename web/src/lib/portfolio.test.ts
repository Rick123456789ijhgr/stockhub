// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  type Action,
  brokerFee,
  DEFAULT_FEES,
  type FeeSettings,
  type Mark,
  netFee,
  nhiPremium,
  type Preview,
  type Receipt,
  replay,
  roundMoney,
  type Security,
  taxRate,
  totals,
  type Trade,
  transactionTax,
  upcoming,
  withPreviews,
} from "./portfolio";

/** The fixture is written by Python (snake_case); the TS port uses camelCase. */
function camel(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camel);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k.replace(/_([a-z])/g, (_, c) => c.toUpperCase()), camel(v)]),
    );
  }
  return value;
}

type ReplayCase = {
  name: string;
  trades: Trade[];
  actions: Action[];
  asOf: string;
  marks: Record<string, Mark>;
  securities: Record<string, Security>;
  fees: FeeSettings;
  previews: Preview[];
  expected: unknown;
};

type Fixture = {
  fees: { settings: FeeSettings; amount: number; quantity: number; expected: unknown }[];
  tax: {
    type: string;
    symbol: string;
    date: string;
    dayTrade: boolean;
    amount: number;
    expected: { rate: number; tax: number };
  }[];
  nhi: { cash: number; stockShares: number; exDate: string; expected: number }[];
  replay: ReplayCase[];
};

// Shared with py/tests/engine/test_portfolio.py (CLAUDE.md rule 11).
const raw = JSON.parse(
  readFileSync(new URL("../../../testdata/portfolio.json", import.meta.url), "utf-8"),
) as { replay: { receipts: Record<string, Receipt> }[] };
const fixture = camel(raw) as Fixture;
// Receipt keys embed the action type ("1|2026-04-23|cash_dividend"): keep them as written.
const receipts = raw.replay.map((c) => c.receipts);

function expectClose(actual: unknown, expected: unknown, path: string) {
  if (Array.isArray(expected)) {
    expect(Array.isArray(actual), path).toBe(true);
    expect((actual as unknown[]).length, path).toBe(expected.length);
    expected.forEach((e, i) => expectClose((actual as unknown[])[i], e, `${path}[${i}]`));
  } else if (expected && typeof expected === "object") {
    const a = actual as Record<string, unknown>;
    expect(Object.keys(a).sort(), path).toEqual(Object.keys(expected).sort());
    for (const [k, e] of Object.entries(expected)) expectClose(a[k], e, `${path}.${k}`);
  } else if (typeof expected === "number") {
    expect(typeof actual, path).toBe("number");
    const tolerance = Math.max(1e-9, 1e-12 * Math.abs(expected));
    expect(Math.abs((actual as number) - expected), path).toBeLessThanOrEqual(tolerance);
  } else {
    expect(actual, path).toBe(expected);
  }
}

describe("portfolio math matches the Python reference", () => {
  it("fees", () => {
    fixture.fees.forEach((c, i) =>
      expect(brokerFee(c.amount, c.quantity, c.settings), `fees[${i}]`).toEqual(c.expected),
    );
  });

  it("tax", () => {
    fixture.tax.forEach((c, i) => {
      const rate = taxRate(c.type, c.symbol, c.date, c.dayTrade);
      expect(rate, `tax[${i}]`).toBe(c.expected.rate);
      expect(transactionTax(c.amount, rate), `tax[${i}]`).toBe(c.expected.tax);
    });
  });

  it("nhi", () => {
    fixture.nhi.forEach((c, i) =>
      expect(nhiPremium(c.cash, c.stockShares, c.exDate), `nhi[${i}]`).toBe(c.expected),
    );
  });

  it.each(fixture.replay.map((c, i) => [c.name, c, i] as const))("replay: %s", (_name, c, i) => {
    const ledger = replay(c.trades, withPreviews(c.actions, c.previews, c.asOf), {
      asOf: c.asOf,
      marks: c.marks,
      securities: c.securities,
      fees: c.fees,
      receipts: receipts[i],
    });
    expectClose(
      {
        ledger,
        totals: totals(ledger.positions),
        upcoming: upcoming(ledger.positions, c.previews, c.asOf),
      },
      c.expected,
      c.name,
    );
  });
});

describe("hand-checked cases", () => {
  it("rounds away float noise", () => {
    expect(1.15 * 100).not.toBe(115);
    expect(roundMoney(1.15 * 100)).toBe(115);
    expect(roundMoney(100_000 * 0.001425, "round")).toBe(143);
  });

  it("rebate mode charges the full fee and refunds the discount", () => {
    const s: FeeSettings = { ...DEFAULT_FEES, discount: 0.28, discountMode: "rebate" };
    expect(brokerFee(100_000, 1000, s)).toEqual({ fee: 142, rebate: 103 });
    expect(netFee(100_000, 1000, s)).toBe(39);
  });

  it("reports oversells instead of going short", () => {
    const t = (id: string, side: "buy" | "sell", quantity: number): Trade => ({
      id,
      stock: "A",
      date: "2026-01-05",
      side,
      quantity,
      price: 10,
      fee: 0,
      tax: 0,
      rebate: 0,
      dayTrade: false,
    });
    const ledger = replay([t("1", "buy", 1000), t("2", "sell", 1500)], [], { asOf: "2026-10-19" });
    expect(ledger.issues).toEqual([
      { id: "2", stock: "A", date: "2026-01-05", held: 1000, quantity: 1500 },
    ]);
    expect(ledger.positions[0].shares).toBe(1000);
  });
});
