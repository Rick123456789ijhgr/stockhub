import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionStatus } from "@/lib/session-status";

import { SessionClock, SessionPill } from "./session-rail";

const friday: SessionStatus = {
  date: "2026-10-16",
  tradingDay: true,
  nextTradingDay: "2026-10-19",
  lastQuoteAt: "2026-10-16T03:41:30Z",
  lastCloseDate: "2026-10-15",
};

function renderAt(utc: string, status: SessionStatus) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(utc));
  return render(<SessionClock status={status} serverNow={utc} />);
}

describe("SessionClock", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the live session, its time and when quotes last came in", () => {
    renderAt("2026-10-16T03:42:00Z", friday); // 11:42 Taipei
    // Once for the open sidebar, once for the folded rail.
    expect(screen.getAllByText("盤中")).toHaveLength(2);
    expect(screen.getAllByText("11:42")).toHaveLength(2);
    expect(screen.getByText("報價更新 11:41:30")).toBeInTheDocument();
  });

  it("shows a holiday with the next trading day and the latest close", () => {
    renderAt("2026-10-17T03:00:00Z", { ...friday, date: "2026-10-17", tradingDay: false, lastQuoteAt: null });
    expect(screen.getAllByText("休市")).toHaveLength(2);
    expect(screen.getByText("下個交易日 10/19（一）")).toBeInTheDocument();
    expect(screen.getByText("最新收盤 10/15")).toBeInTheDocument();
  });

  it("falls back to the close when the page stayed open past the quote's day", () => {
    renderAt("2026-10-17T01:00:00Z", friday); // Saturday morning, status still Friday's
    expect(screen.getAllByText("休市")).toHaveLength(2);
    expect(screen.getByText("最新收盤 10/15")).toBeInTheDocument();
  });

  it("fits the phone top bar with the phase and a short next day", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-17T03:00:00Z"));
    render(
      <SessionPill
        status={{ ...friday, date: "2026-10-17", tradingDay: false, lastQuoteAt: null }}
        serverNow="2026-10-17T03:00:00Z"
      />,
    );
    expect(screen.getByText("休市")).toBeInTheDocument();
    expect(screen.getByText("下個交易日 10/19（一）")).toBeInTheDocument();
  });
});
