"use client";

import { useSyncExternalStore } from "react";

import { formatTaipeiDateTime } from "@/lib/format";
import {
  CLOSING_AUCTION_AT,
  OPEN_AT,
  PHASE_LABEL,
  RAIL_END,
  RAIL_START,
  type SessionPhase,
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

type SessionView = {
  phase: SessionPhase;
  progress: number;
  live: boolean;
  label: string;
  /** Clock time, or the next trading day on a holiday. */
  detail: string;
  /** Clock time only ("" on a holiday): the short form for the collapsed rail. */
  time: string;
  freshness: string | null;
};

export type SessionProps = { status: SessionStatus; serverNow: string };

function useSession({ status, serverNow }: SessionProps): SessionView {
  const now = useNow(serverNow);
  const { phase, progress } = sessionPhase(now, status);
  const live = phase === "continuous" || phase === "closingAuction" || phase === "trial";
  // The status is today's quotes only; a page left open overnight falls back to the close.
  const quoteToday = status.lastQuoteAt !== null && taipeiToday(now) === status.date;
  const freshness =
    status.lastQuoteAt && quoteToday
      ? `報價更新 ${formatTaipeiDateTime(status.lastQuoteAt).slice(11)}`
      : status.lastCloseDate
        ? `最新收盤 ${status.lastCloseDate.slice(5).replace("-", "/")}`
        : null;
  const time = phase === "holiday" ? "" : formatTaipeiDateTime(now).slice(11, 16);
  const detail =
    phase === "holiday"
      ? status.nextTradingDay
        ? `下個交易日 ${shortDate(status.nextTradingDay)}`
        : ""
      : time;
  return { phase, progress, live, label: PHASE_LABEL[phase], detail, time, freshness };
}

/**
 * The session as a ring around the brand mark (D-128): the arc fills from 08:30 to 13:30 in
 * the brand color while the market is live, stays grey before and after, and is dashed on
 * holidays. With the timeline in the sidebar, this arc is the one piece of motion nobody
 * triggers: it moves every 30 s.
 */
export function SessionRing({ children, ...props }: SessionProps & { children: React.ReactNode }) {
  const s = useSession(props);
  const filled = s.phase === "closed" ? 100 : s.phase === "holiday" ? 0 : s.progress * 100;
  return (
    <span
      className="relative grid size-9 shrink-0 place-items-center"
      title={[s.label, s.detail, s.freshness].filter(Boolean).join("，")}
    >
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle
          cx="18"
          cy="18"
          r="16.5"
          fill="none"
          strokeWidth="2"
          className="stroke-border"
          strokeDasharray={s.phase === "holiday" ? "2 3.2" : undefined}
        />
        {filled > 0 ? (
          <circle
            cx="18"
            cy="18"
            r="16.5"
            fill="none"
            strokeWidth="2"
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray={`${filled} 100`}
            className={cn(
              "transition-[stroke-dasharray] duration-1000 ease-linear",
              s.live ? "stroke-brand" : "stroke-muted-foreground/50",
            )}
          />
        ) : null}
      </svg>
      {children}
    </span>
  );
}

/**
 * The Taiwan session in the sidebar (D-128): phase and time, a rail from the trial match to
 * the close with the elapsed part filled, and how fresh the numbers on the page are. In the
 * collapsed rail only the phase and time show, stacked.
 */
export function SessionClock(props: SessionProps) {
  const s = useSession(props);
  return (
    <section aria-label="交易時段" className="relative h-[3.25rem] text-xs">
      {/* Collapsed rail: two short lines centered in the 3.5rem column. */}
      <p className="nav-conceal absolute inset-y-0 left-0 flex w-10 flex-col items-center justify-center text-[10px] leading-tight tabular-nums">
        <span className={cn("font-semibold", s.live ? "text-brand" : "text-muted-foreground")}>
          {s.phase === "closingAuction" ? "收盤" : s.label}
        </span>
        <span className="text-muted-foreground">{s.time}</span>
      </p>

      <div className="nav-reveal absolute inset-0 flex flex-col justify-center gap-1.5 px-3">
        <p className="flex items-baseline gap-2 whitespace-nowrap">
          <span className={cn("text-sm font-semibold", s.live ? "text-foreground" : "text-muted-foreground")}>
            {s.label}
          </span>
          <span className="truncate text-muted-foreground tabular-nums">{s.detail}</span>
        </p>
        <div className={cn("relative h-1.5", s.phase === "holiday" && "opacity-40")} aria-hidden>
          <div className="absolute inset-0 rounded-full bg-border" />
          <div
            className={cn(
              "absolute inset-y-0 left-0 rounded-full transition-[width] duration-1000 ease-linear",
              s.live ? "bg-brand" : "bg-muted-foreground/40",
            )}
            style={{ width: `${(s.phase === "closed" ? 1 : s.progress) * 100}%` }}
          />
          <div
            className="absolute inset-y-0 right-0 rounded-r-full bg-muted-foreground/45"
            style={{ left: at(CLOSING_AUCTION_AT) }}
            title="13:25–13:30 收盤集合競價"
          />
          <div className="absolute -inset-y-0.5 w-px bg-muted-foreground/70" style={{ left: at(OPEN_AT) }} title="09:00 開盤" />
        </div>
        <p className="truncate text-[11px] text-muted-foreground tabular-nums">{s.freshness}</p>
      </div>
    </section>
  );
}

/** Phones: the phase and time next to the brand in the top bar. */
export function SessionPill(props: SessionProps) {
  const s = useSession(props);
  return (
    <p
      aria-label="交易時段"
      className="flex items-baseline gap-1.5 text-xs tabular-nums"
      title={s.freshness ?? undefined}
    >
      <span className={cn("font-semibold", s.live ? "text-brand" : "text-muted-foreground")}>{s.label}</span>
      <span className="text-muted-foreground">{s.phase === "holiday" ? s.detail : s.time}</span>
    </p>
  );
}
