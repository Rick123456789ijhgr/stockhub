"use client";

import Link from "next/link";
import { useState } from "react";

import { SEGMENTED_GROUP, segmentedOption } from "@/components/segmented-links";
import { directionClass } from "@/components/price-change";
import type { MarketFlow, RankedFlow, RankingGroup } from "@/lib/chips";
import { barPercent, flowScale, formatYi } from "@/lib/flow-chart";
import { cn } from "@/lib/utils";

export type GroupRankings = Record<RankingGroup, { buys: RankedFlow[]; sells: RankedFlow[] }>;

const MARKET_LABEL = { twse: "上市", tpex: "上櫃" } as const;
const GROUP_LABEL: Record<RankingGroup, string> = {
  total: "三大法人",
  foreign: "外資",
  trust: "投信",
  dealer: "自營商",
};
const PARTS = ["foreign", "trust", "dealer"] as const;

function shortDate(date: string): string {
  return date.slice(5).replace("-", "/");
}

function Yi({ value, className }: { value: number | null; className?: string }) {
  if (value === null) return <span className={cn("text-muted-foreground", className)}>—</span>;
  return <span className={cn("tabular-nums", directionClass(value), className)}>{formatYi(value)}</span>;
}

/**
 * One market's flows: a bar per group growing left (net sell) or right (net buy) from the
 * zero line, on that market's own scale (TWSE flows are ten times TPEx's).
 */
function MarketFlows({ flow }: { flow: MarketFlow }) {
  const scale = flowScale(PARTS.map((p) => flow[p]));
  return (
    <figure className="min-w-0 space-y-2">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">
          {MARKET_LABEL[flow.market]}
          <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">{shortDate(flow.tradeDate)}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          合計 <Yi value={flow.total} className="text-base font-semibold" /> 億
        </span>
      </figcaption>
      <ul className="space-y-1.5 text-xs">
        {PARTS.map((part) => {
          const value = flow[part];
          const width = barPercent(value, scale);
          const buy = value !== null && value > 0;
          return (
            <li
              key={part}
              className="grid grid-cols-[3rem_minmax(0,1fr)_4.5rem] items-center gap-2"
              title={value === null ? undefined : `${MARKET_LABEL[flow.market]}${GROUP_LABEL[part]}${buy ? "買超" : "賣超"} ${formatYi(value)} 億`}
            >
              <span className="text-muted-foreground">{GROUP_LABEL[part]}</span>
              {/* Two half tracks around the zero line. */}
              <span className="relative grid h-3 grid-cols-2" aria-hidden>
                <span className="absolute inset-y-[-3px] left-1/2 w-px bg-border" />
                <span className="flex justify-end pr-px">
                  {!buy && width > 0 ? (
                    <span className="h-full rounded-l-[4px] bg-down/85" style={{ width: `${width}%` }} />
                  ) : null}
                </span>
                <span className="flex pl-px">
                  {buy ? <span className="h-full rounded-r-[4px] bg-up/85" style={{ width: `${width}%` }} /> : null}
                </span>
              </span>
              <Yi value={value} className="text-right" />
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

/**
 * A ranked stock as a bar from the zero line with its amount at the bar's end. On wider
 * screens the two columns meet at the zero line: sells grow left, buys grow right, names on
 * the outer edges (a butterfly chart). On phones both lists read name first, bar after.
 */
function RankRow({ row, rank, scale, side }: { row: RankedFlow; rank: number; scale: number; side: "buy" | "sell" }) {
  const sell = side === "sell";
  const lots = Math.round(row.netShares / 1000).toLocaleString("zh-TW");
  return (
    <li>
      <Link
        href={`/stocks/${row.symbol}?tab=chips`}
        title={`${row.symbol} ${row.name}：${sell ? "賣超" : "買超"} ${lots} 張，收盤 ${row.close}，估計 ${formatYi(row.netValue)} 億`}
        className={cn(
          "grid h-8 grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)] items-center gap-3 rounded-md px-1.5 text-sm hover:bg-accent",
          sell ? "sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]" : "sm:grid-cols-[minmax(0,1fr)_minmax(0,11rem)]",
        )}
      >
        <span className={cn("flex min-w-0 items-baseline gap-1.5", !sell && "sm:order-2")}>
          <span className="w-4 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums">{rank}</span>
          <span className="truncate">
            <span className="text-xs font-semibold tabular-nums">{row.symbol}</span> {row.name}
          </span>
        </span>
        <span className={cn("flex min-w-0 items-center gap-1.5", sell && "sm:flex-row-reverse")}>
          <span
            aria-hidden
            className={cn(
              "h-2.5 shrink-0 rounded-r-[4px]",
              sell ? "bg-down/85 sm:rounded-r-none sm:rounded-l-[4px]" : "bg-up/85",
            )}
            // The amount after the bar takes up to 3.5rem of the cell.
            style={{ width: `calc((100% - 3.5rem) * ${barPercent(row.netValue, scale) / 100})` }}
          />
          <Yi value={row.netValue} className="shrink-0 text-xs" />
        </span>
      </Link>
    </li>
  );
}

function RankColumn({ title, rows, scale, side }: { title: string; rows: RankedFlow[]; scale: number; side: "buy" | "sell" }) {
  return (
    <div className="min-w-0">
      <h3 className={cn("mb-1 px-1.5 text-xs text-muted-foreground", side === "sell" && "sm:text-right")}>{title}</h3>
      {rows.length === 0 ? (
        <p className="px-1.5 text-sm text-muted-foreground">—</p>
      ) : (
        <ol>
          {rows.map((row, i) => (
            <RankRow key={row.symbol} row={row} rank={i + 1} scale={scale} side={side} />
          ))}
        </ol>
      )}
    </div>
  );
}

export function FlowBoard({
  flows,
  rankings,
  tradeDate,
}: {
  flows: MarketFlow[];
  rankings: GroupRankings;
  tradeDate: string | null;
}) {
  const [group, setGroup] = useState<RankingGroup>("total");
  const { buys, sells } = rankings[group];
  // Buys and sells share one scale, so the longest bar on either side is the day's largest.
  const scale = flowScale([...buys, ...sells].map((r) => r.netValue));
  return (
    <div className="space-y-6">
      {flows.length > 0 ? (
        <div className="grid gap-x-10 gap-y-5 md:grid-cols-2">
          {flows.map((flow) => (
            <MarketFlows key={flow.market} flow={flow} />
          ))}
        </div>
      ) : null}

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div role="radiogroup" aria-label="法人" className={cn(SEGMENTED_GROUP, "text-xs")}>
            {(Object.keys(GROUP_LABEL) as RankingGroup[]).map((key) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={group === key}
                className={segmentedOption(group === key)}
                onClick={() => setGroup(key)}
              >
                {GROUP_LABEL[key]}
              </button>
            ))}
          </div>
          {tradeDate ? (
            <span className="text-xs text-muted-foreground tabular-nums">個股排行 {shortDate(tradeDate)}，估計金額（億）</span>
          ) : null}
        </div>
        {/* The border between the columns is the zero line both sides grow from. */}
        <div className="grid gap-y-4 sm:grid-cols-2">
          <div className="sm:border-r sm:pr-2">
            <RankColumn title={`${GROUP_LABEL[group]}賣超`} rows={sells} scale={scale} side="sell" />
          </div>
          <div className="sm:pl-2">
            <RankColumn title={`${GROUP_LABEL[group]}買超`} rows={buys} scale={scale} side="buy" />
          </div>
        </div>
      </div>
    </div>
  );
}
