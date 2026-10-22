/**
 * Validation of /admin theme and macro-event requests (pure). The tables' CHECKs and
 * unique keys guard the rest.
 */

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const SYMBOL = /^[0-9A-Z]{4,6}$/;

export function isRealDate(value: unknown): value is string {
  if (typeof value !== "string" || !DATE.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

const text = (value: unknown, max: number): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed && trimmed.length <= max ? trimmed : null;
};

const optionalText = (value: unknown, max: number): string | null | undefined => {
  if (value === undefined || value === null || value === "") return null;
  return text(value, max) ?? undefined;
};

const body = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

export type ThemeInput = { name: string; description: string | null };

export function parseThemeInput(value: unknown): ThemeInput | null {
  const raw = body(value);
  const name = text(raw.name, 40);
  const description = optionalText(raw.description, 500);
  if (!name || description === undefined) return null;
  return { name, description };
}

export type MemberInput = { symbol: string; validFrom: string; note: string | null };

export function parseMemberInput(value: unknown, today: string): MemberInput | null {
  const raw = body(value);
  const symbol = typeof raw.symbol === "string" ? raw.symbol.trim().toUpperCase() : "";
  const validFrom = raw.validFrom ?? today;
  const note = optionalText(raw.note, 200);
  if (!SYMBOL.test(symbol) || !isRealDate(validFrom) || note === undefined) return null;
  return { symbol, validFrom, note };
}

/** Ending (validTo set) or deleting one membership period, identified by its key. */
export type MemberKey = { stockId: string; validFrom: string; validTo?: string | null };

export function parseMemberKey(value: unknown, needsEnd: boolean): MemberKey | null {
  const raw = body(value);
  const stockId =
    typeof raw.stockId === "string" || typeof raw.stockId === "number" ? String(raw.stockId) : "";
  if (!/^\d+$/.test(stockId) || !isRealDate(raw.validFrom)) return null;
  if (!needsEnd) return { stockId, validFrom: raw.validFrom };
  if (!isRealDate(raw.validTo) || raw.validTo < raw.validFrom) return null;
  return { stockId, validFrom: raw.validFrom, validTo: raw.validTo };
}

export type Period = { validFrom: string; validTo: string | null };

/** Whether [from, to] (null = open) overlaps any existing period of the same stock and theme. */
export function overlaps(periods: readonly Period[], from: string, to: string | null = null): boolean {
  return periods.some((p) => (p.validTo === null || p.validTo >= from) && (to === null || p.validFrom <= to));
}

export const EVENT_KINDS = ["fomc", "cbc", "ndc_signal", "other"] as const;
export type EventKind = (typeof EVENT_KINDS)[number];
export type EventInput = { date: string; kind: EventKind; title: string; note: string | null };

export function parseEventInput(value: unknown): EventInput | null {
  const raw = body(value);
  const title = text(raw.title, 100);
  const note = optionalText(raw.note, 300);
  const kind = raw.kind as EventKind;
  if (!isRealDate(raw.date) || !title || note === undefined || !EVENT_KINDS.includes(kind)) return null;
  return { date: raw.date, kind, title, note };
}
