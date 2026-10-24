import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionStatus } from "@/lib/session-status";

import { SessionRail } from "./session-rail";

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
  return render(<SessionRail status={status} serverNow={utc} />);
}

describe("SessionRail", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the live session, its time and when quotes last came in", () => {
    renderAt("2026-10-16T03:42:00Z", friday); // 11:42 Taipei
    expect(screen.getByText("盤中")).toBeInTheDocument();
    expect(screen.getByText("11:42")).toBeInTheDocument();
    expect(screen.getByText("報價更新 11:41:30")).toBeInTheDocument();
  });

  it("shows a holiday with the next trading day and the latest close", () => {
    renderAt("2026-10-17T03:00:00Z", { ...friday, date: "2026-10-17", tradingDay: false, lastQuoteAt: null });
    expect(screen.getByText("休市")).toBeInTheDocument();
    expect(screen.getByText("下一個交易日 10/19（一）")).toBeInTheDocument();
    expect(screen.getByText("最新收盤 10/15")).toBeInTheDocument();
  });

  it("falls back to the close when the page stayed open past the quote's day", () => {
    renderAt("2026-10-17T01:00:00Z", friday); // Saturday morning, status still Friday's
    expect(screen.getByText("休市")).toBeInTheDocument();
    expect(screen.getByText("最新收盤 10/15")).toBeInTheDocument();
  });
});
