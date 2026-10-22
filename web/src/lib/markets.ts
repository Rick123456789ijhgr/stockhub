import "server-only";

import type { Kysely } from "kysely";

import type { DB } from "@/lib/db";
import type { SeriesCategory, SeriesInfo, SeriesPoint } from "@/lib/market-series";

export type LoadedSeries = SeriesInfo & {
  points: (SeriesPoint & { label: string | null })[];
};

/** Shift a YYYY-MM-DD date by whole days (UTC arithmetic, no time zone involved). */
export function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Enabled series (in display order) with their observations since `since`. */
export async function loadSeries(
  db: Kysely<DB>,
  since: string,
  codes?: readonly string[],
): Promise<LoadedSeries[]> {
  let catalog = db
    .selectFrom("market_series")
    .select(["code", "name", "category", "unit", "frequency"])
    .where("enabled", "=", true)
    .orderBy("sort_order");
  if (codes) catalog = catalog.where("code", "in", [...codes]);
  const series = await catalog.execute();
  if (!series.length) return [];
  const values = await db
    .selectFrom("market_series_values")
    .select(["series_code", "obs_date", "value", "label"])
    .where(
      "series_code",
      "in",
      series.map((s) => s.code),
    )
    .where("obs_date", ">=", since)
    .orderBy("obs_date")
    .execute();
  const by = new Map<string, LoadedSeries["points"]>();
  for (const v of values) {
    const list = by.get(v.series_code) ?? [];
    list.push({
      date: String(v.obs_date),
      value: Number(v.value),
      label: v.label,
    });
    by.set(v.series_code, list);
  }
  return series.map((s) => ({
    code: s.code,
    name: s.name,
    category: s.category as SeriesCategory,
    unit: s.unit,
    frequency: s.frequency as SeriesInfo["frequency"],
    points: by.get(s.code) ?? [],
  }));
}

export type MacroEvent = {
  id: number;
  date: string;
  kind: "fomc" | "cbc" | "ndc_signal" | "other";
  title: string;
  note: string | null;
  source: "seed" | "manual" | "auto";
};

export const EVENT_KIND_LABEL: Record<MacroEvent["kind"], string> = {
  fomc: "Fed",
  cbc: "央行",
  ndc_signal: "景氣燈號",
  other: "其他",
};

/** Events from `from` on, oldest first (limit keeps the list short). */
export async function listMacroEvents(db: Kysely<DB>, from: string, limit = 100): Promise<MacroEvent[]> {
  const rows = await db
    .selectFrom("macro_events")
    .select(["id", "event_date", "kind", "title", "note", "source"])
    .where("event_date", ">=", from)
    .orderBy("event_date")
    .orderBy("id")
    .limit(limit)
    .execute();
  return rows.map((r) => ({
    id: Number(r.id),
    date: String(r.event_date),
    kind: r.kind as MacroEvent["kind"],
    title: r.title,
    note: r.note,
    source: r.source as MacroEvent["source"],
  }));
}

export type MarketsStatus = {
  series: {
    code: string;
    name: string;
    frequency: string;
    firstDate: string | null;
    lastDate: string | null;
    observations: number;
  }[];
  quarantinePending: number;
};

/** Per series coverage (market_series_status) and pending quarantine, for /status. */
export async function getMarketsStatus(db: Kysely<DB>): Promise<MarketsStatus> {
  const [rows, pending] = await Promise.all([
    db
      .selectFrom("market_series_status as v")
      .innerJoin("market_series as s", "s.code", "v.code")
      .select(["v.code", "v.name", "v.frequency", "v.first_date", "v.last_date", "v.observations"])
      .where("v.enabled", "=", true)
      .orderBy("s.sort_order")
      .execute(),
    db
      .selectFrom("market_series_quarantine")
      .select((eb) => eb.fn.countAll<string>().as("n"))
      .where("resolved_at", "is", null)
      .executeTakeFirst(),
  ]);
  return {
    series: rows.map((r) => ({
      code: String(r.code),
      name: String(r.name),
      frequency: String(r.frequency),
      firstDate: r.first_date === null ? null : String(r.first_date),
      lastDate: r.last_date === null ? null : String(r.last_date),
      observations: Number(r.observations ?? 0),
    })),
    quarantinePending: Number(pending?.n ?? 0),
  };
}
