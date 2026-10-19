/** Fee settings validation and labels (safe for client components). */

import { DEFAULT_FEES, type DiscountMode, type FeeSettings, type Rounding } from "@/lib/portfolio";

export const DISCOUNT_MODE_LABEL: Record<DiscountMode, string> = {
  instant: "成交時直接折抵",
  rebate: "先收全額，事後退還",
};

export const ROUNDING_LABEL: Record<Rounding, string> = {
  floor: "元以下捨去",
  round: "四捨五入",
};

const LIMITS = {
  rate: [0, 0.01],
  discount: [0, 1],
  minFee: [0, 1000],
} as const;

function num(value: unknown): number | null {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

/**
 * Validate a PUT body (or a stored value); null when anything is out of range. The rate
 * and discount are fractions (0.001425, 0.28), minimums whole TWD.
 */
export function parseFeeSettings(body: unknown): FeeSettings | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;
  const rate = num(b.rate);
  const discount = num(b.discount);
  const minFee = num(b.minFee);
  const minFeeOddLot = num(b.minFeeOddLot);
  if (rate === null || rate <= LIMITS.rate[0] || rate > LIMITS.rate[1]) return null;
  if (discount === null || discount <= LIMITS.discount[0] || discount > LIMITS.discount[1]) {
    return null;
  }
  for (const m of [minFee, minFeeOddLot]) {
    if (m === null || !Number.isInteger(m) || m < LIMITS.minFee[0] || m > LIMITS.minFee[1]) {
      return null;
    }
  }
  if (b.discountMode !== "instant" && b.discountMode !== "rebate") return null;
  if (b.rounding !== "floor" && b.rounding !== "round") return null;
  return {
    rate,
    discount,
    minFee: minFee as number,
    minFeeOddLot: minFeeOddLot as number,
    discountMode: b.discountMode,
    rounding: b.rounding,
  };
}

/** The stored settings row, or the defaults when it is missing or invalid. */
export function feeSettingsFromStored(value: unknown): FeeSettings {
  return parseFeeSettings(value) ?? DEFAULT_FEES;
}

/** 0.28 -> "2.8 折"; 1 -> "無折扣". */
export function describeDiscount(discount: number): string {
  if (discount >= 1) return "無折扣";
  return `${Number((discount * 10).toFixed(3))} 折`;
}

/** One-line summary, e.g. "0.1425% × 2.8 折，最低 20 元（零股 1 元），成交時直接折抵". */
export function describeFeeSettings(s: FeeSettings): string {
  const rate = `${Number((s.rate * 100).toFixed(4))}%`;
  const discount = s.discount >= 1 ? "" : ` × ${describeDiscount(s.discount)}`;
  const mode = s.discount >= 1 ? "" : `，${DISCOUNT_MODE_LABEL[s.discountMode]}`;
  return `${rate}${discount}，最低 ${s.minFee} 元（零股 ${s.minFeeOddLot} 元）${mode}，${ROUNDING_LABEL[s.rounding]}`;
}
