import { Pnl } from "@/components/portfolio/holdings";
import { PriceChange } from "@/components/price-change";
import { formatInteger } from "@/lib/format";
import type { Totals } from "@/lib/portfolio";

/** Headline numbers: value, unrealized, today, realized, dividends, total. */
export function PortfolioSummary({ totals }: { totals: Totals }) {
  const previous = totals.marketValue - totals.dayChange;
  const total = totals.unrealized + totals.realized + totals.dividends + totals.rebates;
  const items = [
    {
      label: "市值",
      value: <span className="tabular-nums">{formatInteger(Math.round(totals.marketValue))}</span>,
      sub: `成本 ${formatInteger(Math.round(totals.cost))}`,
    },
    {
      label: "今日損益",
      value: <Pnl value={totals.dayChange} />,
      sub:
        previous > 0 ? <PriceChange value={(totals.dayChange / previous) * 100} suffix="%" /> : null,
    },
    {
      label: "未實現損益",
      value: <Pnl value={totals.unrealized} />,
      sub:
        totals.cost > 0 ? (
          <PriceChange value={(totals.unrealized / totals.cost) * 100} suffix="%" />
        ) : null,
    },
    { label: "已實現損益", value: <Pnl value={totals.realized} />, sub: "已扣手續費與證交稅" },
    {
      label: "股利（估）",
      value: <Pnl value={totals.dividends} />,
      sub: totals.rebates > 0 ? `另有退佣（估）${formatInteger(totals.rebates)}` : "現金股利與退還股款",
    },
    { label: "總損益", value: <Pnl value={total} />, sub: "未實現 + 已實現 + 股利 + 退佣" },
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg bg-muted/60 p-3 transition-colors duration-150 hover:bg-muted">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-1 text-lg font-semibold">{item.value}</dd>
          <dd className="text-xs text-muted-foreground">{item.sub}</dd>
        </div>
      ))}
    </dl>
  );
}
