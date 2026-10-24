/**
 * Bar geometry for the institutional flow charts on the home page (D-130): diverging bars
 * from a zero line, all bars of one chart on one scale so lengths compare.
 */

/** The largest absolute value, the length of a full bar; 0 when there is nothing to draw. */
export function flowScale(values: readonly (number | null)[]): number {
  return values.reduce<number>((max, v) => (v === null ? max : Math.max(max, Math.abs(v))), 0);
}

/** Smallest visible bar (% of the track) for a value that is not zero. */
const MIN_BAR = 1.5;

/** Bar length as a percentage of the track (0..100). */
export function barPercent(value: number | null, scale: number): number {
  if (value === null || value === 0 || scale <= 0) return 0;
  return Math.max(MIN_BAR, Math.min(100, (Math.abs(value) / scale) * 100));
}

/** TWD to 億 with one decimal and a sign, as the exchanges print flows. */
export function formatYi(value: number): string {
  const yi = value / 1e8;
  const text = Math.abs(yi).toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (text === "0.0") return "0.0";
  return `${yi > 0 ? "+" : "-"}${text}`;
}
