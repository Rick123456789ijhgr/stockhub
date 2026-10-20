/** Value and period formatting shared by the fundamentals charts and tables. */

export type ValueFormat = "percent" | "price" | "ratio" | "hundredMillion" | "eps";
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
  }
}

export function axisFormat(value: number, format: ValueFormat): string {
  if (format === "percent") return `${(value * 100).toFixed(0)}%`;
  if (format === "hundredMillion") return `${(value / 1e8).toFixed(0)}`;
  if (format === "ratio") return value.toFixed(1);
  return value.toFixed(value >= 100 ? 0 : 2);
}
