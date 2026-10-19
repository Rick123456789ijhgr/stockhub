"use client";

import { useState } from "react";

import type { Cell, CellState, MonthRow } from "@/lib/coverage-grid";
import { cn } from "@/lib/utils";

export const STATE_CLASS: Record<CellState, string> = {
  full: "bg-coverage-full",
  partial: "bg-coverage-partial",
  gap: "bg-coverage-gap",
  closed: "bg-coverage-closed",
  notFetched: "border border-coverage-empty",
  future: "",
};

export const STATE_LABEL: Record<CellState, string> = {
  full: "上市、上櫃都有資料",
  partial: "只有一個市場有資料",
  gap: "缺漏：回填範圍內的交易日卻沒有資料",
  closed: "休市",
  notFetched: "尚未回填",
  future: "尚未到來或尚未公布",
};

const nf = new Intl.NumberFormat("en-US");

function describe(cell: Cell): string {
  const { day, state } = cell;
  if (state === "full" || state === "partial") {
    return `${day.date}：上市 ${nf.format(day.twse)} 筆、上櫃 ${nf.format(day.tpex)} 筆`;
  }
  return `${day.date}：${STATE_LABEL[state]}`;
}

const DAY_TICKS = new Set([1, 5, 10, 15, 20, 25, 31]);

/** Month × day-of-month grid; hover, focus or tap a cell to read that day's counts. */
export function CoverageGrid({ rows }: { rows: MonthRow[] }) {
  const [active, setActive] = useState<Cell | null>(null);

  return (
    <div>
      <div
        className="grid gap-[2px] text-[10px] text-muted-foreground"
        style={{ gridTemplateColumns: "2rem repeat(31, minmax(0, 1fr))" }}
        role="grid"
        aria-label="每日資料涵蓋，列為月份、欄為日期"
      >
        <div />
        {Array.from({ length: 31 }, (_, i) => (
          <div key={i} className="text-center tabular-nums" aria-hidden>
            {DAY_TICKS.has(i + 1) ? i + 1 : ""}
          </div>
        ))}
        {rows.map((row) => (
          <Row key={row.month} row={row} onSelect={setActive} active={active} />
        ))}
      </div>
      <p className="mt-2 min-h-5 text-sm tabular-nums" aria-live="polite">
        {active ? describe(active) : <span className="text-muted-foreground">點選或滑過格子查看當天筆數</span>}
      </p>
    </div>
  );
}

function Row({
  row,
  active,
  onSelect,
}: {
  row: MonthRow;
  active: Cell | null;
  onSelect: (cell: Cell) => void;
}) {
  return (
    <>
      <div className="flex items-center pr-1 tabular-nums" role="rowheader">
        {row.month}月
      </div>
      {row.cells.map((cell, i) =>
        cell ? (
          <button
            key={i}
            type="button"
            title={describe(cell)}
            aria-label={describe(cell)}
            onMouseEnter={() => onSelect(cell)}
            onFocus={() => onSelect(cell)}
            onClick={() => onSelect(cell)}
            className={cn(
              // The button is the hit target; the swatch inside keeps a 2px surface gap.
              "aspect-square rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring",
              STATE_CLASS[cell.state],
              active?.day.date === cell.day.date && "ring-2 ring-foreground/60",
            )}
          />
        ) : (
          <div key={i} aria-hidden />
        ),
      )}
    </>
  );
}

export function CoverageLegend() {
  const items: CellState[] = ["full", "partial", "gap", "notFetched", "closed"];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((state) => (
        <li key={state} className="flex items-center gap-1.5">
          <span className={cn("inline-block size-3 rounded-[3px]", STATE_CLASS[state])} aria-hidden />
          {state === "gap" ? "⚠ 缺漏" : STATE_LABEL[state].split("：")[0]}
        </li>
      ))}
    </ul>
  );
}
