import Link from "next/link";
import type { ReactNode } from "react";

import { direction, PriceChange } from "@/components/price-change";
import { Badge } from "@/components/ui/badge";
import { formatInteger, formatPrice, formatTaipeiDateTime } from "@/lib/format";
import type { DividendEntry, Position, RealizedEntry } from "@/lib/portfolio";
import type { MarkInfo, StockRef } from "@/lib/portfolio-data";
import { cn } from "@/lib/utils";

const ARROW = { up: "▲", down: "▼", flat: "" } as const;
const COLOR = { up: "text-up", down: "text-down", flat: "text-flat" } as const;

/** A signed whole-TWD amount colored by direction (arrow keeps it readable without color). */
export function Pnl({ value, className }: { value: number | null; className?: string }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const rounded = Math.round(value);
  const dir = direction(rounded);
  return (
    <span className={cn("tabular-nums", COLOR[dir], className)}>
      {ARROW[dir]}
      {formatInteger(Math.abs(rounded))}
    </span>
  );
}

function pct(numerator: number | null, denominator: number | null): number | null {
  if (numerator === null || denominator === null || denominator === 0) return null;
  return (numerator / denominator) * 100;
}

function MarkLabel({ mark }: { mark: MarkInfo | undefined }) {
  if (!mark) return <span>無價格</span>;
  if (mark.source === "quote") {
    return <span>盤中 {formatTaipeiDateTime(mark.quoteTime).slice(11, 16)}</span>;
  }
  return <span>{mark.date} 收盤</span>;
}

function StockName({ stock }: { stock: StockRef | undefined }) {
  if (!stock) return null;
  return (
    <Link href={`/stocks/${stock.symbol}`} className="font-medium hover:underline">
      <span className="font-mono">{stock.symbol}</span> {stock.name}
      {stock.delistedDate ? <span className="ml-1 text-xs text-muted-foreground">已下市</span> : null}
    </Link>
  );
}

/** Open positions: cards on phones, a table from md up. */
export function HoldingsTable({
  positions,
  stocks,
  marks,
}: {
  positions: Position[];
  stocks: Record<string, StockRef>;
  marks: Record<string, MarkInfo>;
}) {
  if (positions.length === 0) {
    return <p className="text-sm text-muted-foreground">目前沒有持股。</p>;
  }
  return (
    <>
      <ul className="divide-y md:hidden">
        {positions.map((p) => {
          const mark = marks[p.stock];
          const move = mark && mark.prevClose ? pct(mark.price - mark.prevClose, mark.prevClose) : null;
          return (
            <li key={p.stock} className="space-y-1 py-2 text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <StockName stock={stocks[p.stock]} />
                <span className="tabular-nums">
                  {p.price !== null ? formatPrice(String(p.price)) : "—"}{" "}
                  {move !== null ? <PriceChange value={move} suffix="%" className="text-xs" /> : null}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1 text-xs">
                <Cell label="股數" value={formatInteger(p.shares)} />
                <Cell label="均價" value={p.avgCost !== null ? formatPrice(String(p.avgCost)) : "—"} />
                <Cell label="市值" value={p.marketValue !== null ? formatInteger(Math.round(p.marketValue)) : "—"} />
                <Cell label="今日" value={<Pnl value={p.dayChange} />} />
                <Cell label="未實現" value={<Pnl value={p.unrealized} />} />
                <Cell
                  label="報酬率"
                  value={(() => {
                    const r = pct(p.unrealized, p.cost);
                    return r === null ? "—" : <PriceChange value={r} suffix="%" />;
                  })()}
                />
              </div>
              <div className="text-xs text-muted-foreground">
                <MarkLabel mark={mark} />
                {p.dividends > 0 ? ` · 累計股利（估）${formatInteger(p.dividends)}` : ""}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b text-right [&>th]:px-2 [&>th]:py-2 [&>th]:font-normal">
              <th className="text-left">股票</th>
              <th>股數</th>
              <th>均價</th>
              <th>現價</th>
              <th>今日損益</th>
              <th>市值</th>
              <th>成本</th>
              <th>未實現損益</th>
              <th>報酬率</th>
              <th>累計股利（估）</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {positions.map((p) => {
              const mark = marks[p.stock];
              const move = mark && mark.prevClose ? pct(mark.price - mark.prevClose, mark.prevClose) : null;
              const ret = pct(p.unrealized, p.cost);
              return (
                <tr key={p.stock} className="border-b text-right last:border-0 [&>td]:px-2 [&>td]:py-2">
                  <td className="text-left">
                    <StockName stock={stocks[p.stock]} />
                    <div className="text-xs text-muted-foreground">
                      <MarkLabel mark={mark} />
                    </div>
                  </td>
                  <td>{formatInteger(p.shares)}</td>
                  <td>{p.avgCost !== null ? formatPrice(String(p.avgCost)) : "—"}</td>
                  <td>
                    {p.price !== null ? formatPrice(String(p.price)) : "—"}
                    {move !== null ? (
                      <div className="text-xs">
                        <PriceChange value={move} suffix="%" />
                      </div>
                    ) : null}
                  </td>
                  <td>
                    <Pnl value={p.dayChange} />
                  </td>
                  <td>{p.marketValue !== null ? formatInteger(Math.round(p.marketValue)) : "—"}</td>
                  <td>{formatInteger(Math.round(p.cost))}</td>
                  <td>
                    <Pnl value={p.unrealized} />
                  </td>
                  <td>{ret === null ? "—" : <PriceChange value={ret} suffix="%" />}</td>
                  <td>{p.dividends > 0 ? formatInteger(p.dividends) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Cell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="tabular-nums">{value}</div>
    </div>
  );
}

const ACTION_LABEL: Record<string, string> = {
  cash_dividend: "除息",
  stock_dividend: "除權",
  cash_and_stock_dividend: "除權息",
  capital_reduction: "減資",
  split: "分割",
  reverse_split: "合併",
};

function ratioText(value: number): string {
  return String(Number(value.toFixed(6)));
}

/** Estimated dividends and share changes, newest first. */
export function DividendList({
  dividends,
  stocks,
}: {
  dividends: DividendEntry[];
  stocks: Record<string, StockRef>;
}) {
  if (dividends.length === 0) {
    return <p className="text-sm text-muted-foreground">持有期間沒有除權息或股數變動。</p>;
  }
  return (
    <ul className="divide-y text-sm">
      {[...dividends]
        .sort((a, b) => (a.exDate < b.exDate ? 1 : a.exDate > b.exDate ? -1 : 0))
        .map((d) => {
        const shareChange = d.sharesAfter - d.sharesHeld - d.stockShares;
        return (
          <li key={`${d.stock}-${d.exDate}-${d.actionType}`} className="space-y-0.5 py-2">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-xs text-muted-foreground tabular-nums">{d.exDate}</span>
              <span className="text-xs">{ACTION_LABEL[d.actionType] ?? d.actionType}</span>
              <StockName stock={stocks[d.stock]} />
              <Badge variant="outline">估算</Badge>
              {d.implied ? <Badge variant="secondary">比例由參考價推算</Badge> : null}
            </div>
            <div className="text-xs text-muted-foreground tabular-nums">
              除權息前持有 {formatInteger(d.sharesHeld)} 股
              {d.cash > 0
                ? `，每股 ${ratioText(d.cashPerShare)} 元，${d.actionType === "capital_reduction" ? "退還股款" : "現金股利"} ${formatInteger(d.cash)} 元`
                : ""}
              {d.stockShares > 0 ? `，配股 ${ratioText(d.stockRatio * 1000)}‰ = ${formatInteger(d.stockShares)} 股` : ""}
              {shareChange !== 0
                ? `，股數 × ${ratioText(d.shareRatio)}（${shareChange > 0 ? "+" : ""}${formatInteger(shareChange)} 股）`
                : ""}
              ，之後 {formatInteger(d.sharesAfter)} 股
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Realized P&L per sell, newest first. */
export function RealizedList({
  realized,
  stocks,
}: {
  realized: RealizedEntry[];
  stocks: Record<string, StockRef>;
}) {
  if (realized.length === 0) return <p className="text-sm text-muted-foreground">還沒有賣出。</p>;
  return (
    <ul className="divide-y text-sm">
      {[...realized]
        .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : Number(b.id) - Number(a.id)))
        .map((r) => (
        <li key={r.id} className="flex items-start justify-between gap-3 py-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-xs text-muted-foreground tabular-nums">{r.date}</span>
              <StockName stock={stocks[r.stock]} />
            </div>
            <div className="text-xs text-muted-foreground tabular-nums">
              賣出 {formatInteger(r.quantity)} 股，收入 {formatInteger(Math.round(r.proceeds))}
              ，成本 {formatInteger(Math.round(r.cost))}，費用 {formatInteger(r.fee + r.tax)}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <Pnl value={r.pnl} />
            <div className="text-xs">
              {r.cost > 0 ? <PriceChange value={(r.pnl / r.cost) * 100} suffix="%" /> : null}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
