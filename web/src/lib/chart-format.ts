/** Value and period formatting shared by the fundamentals and chip charts and tables. */

export type ValueFormat = "percent" | "price" | "ratio" | "hundredMillion" | "eps" | "lots" | "score" | "count";
export type Period = "quarter" | "month" | "day";

export function periodLabel(time: string, period: Period): string {
  const [y, m] = time.split("-").map(Number);
  if (period === "quarter") return `${y}Q${Math.ceil(m / 3)}`;
  if (period === "month") return `${y}/${String(m).padStart(2, "0")}`;
  return time.replaceAll("-", "/");
}

export function formatValue(value: number | null | undefined, format: ValueFormat): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  switch (format) {
    case "percent":
      return `${(value * 100).toFixed(1)}%`;
    case "ratio":
      return `${value.toFixed(1)} 倍`;
    case "hundredMillion":
      return `${(value / 1e8).toLocaleString("zh-TW", { maximumFractionDigits: 1 })} 億`;
    case "eps":
      return value.toFixed(2);
    case "price":
      return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
    case "lots":
      return `${Math.round(value / 1000).toLocaleString("zh-TW")} 張`;
    case "score":
      return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
    case "count":
      return `${Math.round(value).toLocaleString("zh-TW")} 則`;
  }
}

export function axisFormat(value: number, format: ValueFormat): string {
  if (format === "percent") return `${(value * 100).toFixed(0)}%`;
  if (format === "hundredMillion") return `${(value / 1e8).toFixed(0)}`;
  if (format === "ratio" || format === "score") return value.toFixed(1);
  if (format === "count") return value.toFixed(0);
  if (format === "lots") {
    const lots = value / 1000;
    return Math.abs(lots) >= 10_000 ? `${(lots / 10_000).toFixed(1)}萬` : lots.toFixed(0);
  }
  return value.toFixed(value >= 100 ? 0 : 2);
}
