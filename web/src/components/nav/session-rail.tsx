"use client";

import { useSyncExternalStore } from "react";

import { formatTaipeiDateTime } from "@/lib/format";
import {
  CLOSING_AUCTION_AT,
  OPEN_AT,
  PHASE_LABEL,
  RAIL_END,
  RAIL_START,
  sessionPhase,
  taipeiToday,
} from "@/lib/market-hours";
import type { SessionStatus } from "@/lib/session-status";
import { cn } from "@/lib/utils";

const TICK_MS = 30_000;
const SPAN = RAIL_END - RAIL_START;
const at = (minutes: number) => `${((minutes - RAIL_START) / SPAN) * 100}%`;
const WEEKDAY = ["日", "一", "二", "三", "四", "五", "六"];

/** The clock in 30 s steps; the server's time during hydration so both renders agree. */
function useNow(serverNow: string): Date {
  const step = useSyncExternalStore(
    (notify) => {
      const id = window.setInterval(notify, TICK_MS);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / TICK_MS),
    () => Math.floor(Date.parse(serverNow) / TICK_MS),
  );
  return new Date(step * TICK_MS);
}

function shortDate(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${m}/${d}（${WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]}）`;
}

/**
 * The Taiwan session at a glance, on every page (D-126): trial match, open, closing auction
 * and close on one rail, a dot at the current time, and how fresh the numbers below are.
 * The dot is the one piece of motion nobody triggers: it moves every 30 s.
 */
export function SessionRail({ status, serverNow }: { status: SessionStatus; serverNow: string }) {
  const now = useNow(serverNow);
  const { phase, progress } = sessionPhase(now, status);
  const live = phase === "continuous" || phase === "closingAuction" || phase === "trial";
  // The status is today's quotes only; a page left open overnight falls back to the close.
  const quoteToday = status.lastQuoteAt !== null && taipeiToday(now) === status.date;
  const freshness = status.lastQuoteAt && quoteToday
    ? `報價更新 ${formatTaipeiDateTime(status.lastQuoteAt).slice(11)}`
    : status.lastCloseDate
      ? `最新收盤 ${status.lastCloseDate.slice(5).replace("-", "/")}`
      : null;

  return (
    <section
      aria-label="交易時段"
      className="mb-6 grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 text-xs md:mb-8"
    >
      <p className="flex items-baseline gap-2">
        <span className={cn("text-sm font-semibold", live ? "text-foreground" : "text-muted-foreground")}>
          {PHASE_LABEL[phase]}
        </span>
        <span className="text-muted-foreground tabular-nums">
          {phase === "holiday"
            ? status.nextTradingDay
              ? `下一個交易日 ${shortDate(status.nextTradingDay)}`
              : ""
            : formatTaipeiDateTime(now).slice(11, 16)}
        </span>
      </p>

      <div className={cn("relative h-5", phase === "holiday" && "opacity-40")} aria-hidden>
        {/* Track, the elapsed part, and the closing auction as a darker tail. */}
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-border" />
        <div
          className="absolute top-1/2 left-0 h-1 -translate-y-1/2 rounded-full bg-muted-foreground/35 transition-[width] duration-1000 ease-linear"
          style={{ width: `${progress * 100}%` }}
        />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-r-full bg-muted-foreground/60"
          style={{ left: at(CLOSING_AUCTION_AT), right: 0 }}
          title="13:25–13:30 收盤集合競價"
        />
        <div className="absolute top-1/2 h-2.5 w-px -translate-y-1/2 bg-muted-foreground/60" style={{ left: at(OPEN_AT) }} />
        {phase === "holiday" ? null : (
          <div
            className={cn(
              "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-background transition-[left] duration-1000 ease-linear",
              live ? "bg-brand" : "border-2 border-muted-foreground bg-background",
            )}
            style={{ left: `${progress * 100}%` }}
          />
        )}
      </div>

      <p className="text-right text-muted-foreground tabular-nums">{freshness}</p>

      {/* Times under the rail; too crowded on phones. */}
      <div className="relative col-start-2 hidden h-4 text-[11px] text-muted-foreground tabular-nums sm:block" aria-hidden>
        <span className="absolute left-0" title="08:30–09:00 試撮">08:30</span>
        <span className="absolute -translate-x-1/2" style={{ left: at(OPEN_AT) }}>
          09:00 開盤
        </span>
        <span className="absolute right-0">13:30 收盤</span>
      </div>
    </section>
  );
}
