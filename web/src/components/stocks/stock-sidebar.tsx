import Link from "next/link";

import { PriceChange } from "@/components/price-change";
import { Section } from "@/components/section";
import { ShowMoreList } from "@/components/show-more";
import { StockSearchForm } from "@/components/stocks/stock-search-form";
import { formatLots, formatPrice } from "@/lib/format";
import { priceChange } from "@/lib/price";
import type { StockListItem } from "@/lib/stocks";
import { cn } from "@/lib/utils";

const PEERS_SHOWN = 10;

/**
 * The right-hand column of a stock's page: search, then the same industry (or, for an
 * ETF, the most traded ETFs) on the latest close, the current stock marked.
 */
export function StockSidebar({
  symbol,
  title,
  note,
  peers,
}: {
  symbol: string;
  title: string | null;
  note: string | null;
  peers: StockListItem[];
}) {
  return (
    <aside className="space-y-6" aria-label="搜尋與同產業個股">
      <StockSearchForm compact />
      {title && peers.length > 0 ? (
        <Section title={title}>
          <div className="space-y-2">
            <div className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] gap-x-3 px-2 text-xs text-muted-foreground">
              <span>股名／代號</span>
              <span className="w-14 text-right">股價</span>
              <span className="w-14 text-right">漲跌幅</span>
              <span className="w-12 text-right">量（張）</span>
            </div>
            <ShowMoreList
              className="divide-y"
              initial={PEERS_SHOWN}
              step={20}
              items={peers.map((p) => (
                <PeerRow key={p.symbol} stock={p} current={p.symbol === symbol} />
              ))}
            />
            {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
          </div>
        </Section>
      ) : null}
    </aside>
  );
}

function PeerRow({ stock, current }: { stock: StockListItem; current: boolean }) {
  const change = priceChange(stock.close, stock.prevClose);
  return (
    <li>
      <Link
        href={`/stocks/${stock.symbol}`}
        aria-current={current ? "page" : undefined}
        className={cn(
          "grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-x-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted",
          current && "bg-brand-soft hover:bg-brand-soft",
        )}
      >
        <span className="min-w-0">
          <span className="block truncate font-medium">{stock.name}</span>
          <span className="block text-xs font-semibold text-muted-foreground tabular-nums">{stock.symbol}</span>
        </span>
        <span className="w-14 text-right tabular-nums">{formatPrice(stock.close)}</span>
        <span className="w-14 text-right">
          {change ? <PriceChange value={change.percent} suffix="%" /> : <span className="text-muted-foreground">—</span>}
        </span>
        <span className="w-12 text-right text-xs text-muted-foreground tabular-nums">{formatLots(stock.volume)}</span>
      </Link>
    </li>
  );
}
