"use client";

import { useState } from "react";

import { TableCell, TableRow } from "@/components/ui/table";

function useShown(total: number, initial: number, step: number | undefined) {
  const [shown, setShown] = useState(initial);
  const more = shown < total;
  return {
    shown,
    more,
    expandable: total > initial,
    toggle: () => setShown(more ? (step ? Math.min(shown + step, total) : total) : initial),
    label: more
      ? step
        ? `再顯示 ${Math.min(step, total - shown)} 筆（共 ${total.toLocaleString("zh-TW")} 筆）`
        : `展開全部（${total.toLocaleString("zh-TW")}）`
      : "收合",
  };
}

const BUTTON = "text-xs text-muted-foreground hover:text-foreground hover:underline";

/**
 * Table rows rendered by the server, of which the first `initial` show; a last row
 * expands the rest. Place inside `<TableBody>`.
 */
export function ShowMoreRows({
  rows,
  initial,
  colSpan,
}: {
  rows: React.ReactNode[];
  initial: number;
  colSpan: number;
}) {
  const s = useShown(rows.length, initial, undefined);
  return (
    <>
      {rows.slice(0, s.shown)}
      {s.expandable ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={colSpan} className="text-center">
            <button type="button" className={BUTTON} onClick={s.toggle}>
              {s.label}
            </button>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

/** List items of which the first `initial` show, then `step` more per click. */
export function ShowMoreList({
  items,
  initial,
  step,
  className,
}: {
  items: React.ReactNode[];
  initial: number;
  step: number;
  className?: string;
}) {
  const s = useShown(items.length, initial, step);
  return (
    <>
      <ul className={className}>{items.slice(0, s.shown)}</ul>
      {s.expandable ? (
        <div className="pt-2 text-center">
          <button type="button" className={BUTTON} onClick={s.toggle}>
            {s.label}
          </button>
        </div>
      ) : null}
    </>
  );
}
