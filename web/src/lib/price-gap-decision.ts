/** Price-gap review on /admin: request validation and labels (safe for client components). */

export const GAP_ACTION_TYPES = ["split", "reverse_split", "capital_reduction"] as const;
export type GapActionType = (typeof GAP_ACTION_TYPES)[number];

export const GAP_ACTION_LABEL: Record<GapActionType, string> = {
  split: "面額變更／分割",
  reverse_split: "面額變更／合併",
  capital_reduction: "減資",
};

/** Same bounds as the Python quality check on a single event factor (0.02～50). */
const MIN_RATIO = 0.02;
const MAX_RATIO = 50;

export type GapDecision =
  | { kind: "confirm"; ratio: number; actionType: GapActionType }
  | { kind: "dismiss" };

/** Validate the POST body of /api/admin/price-gaps/[id]; null when invalid. */
export function parseGapDecision(body: unknown): GapDecision | null {
  if (typeof body !== "object" || body === null) return null;
  const { decision, ratio, actionType } = body as Record<string, unknown>;
  if (decision === "dismiss") return { kind: "dismiss" };
  if (decision !== "confirm") return null;
  const value = typeof ratio === "string" ? Number(ratio) : ratio;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value < MIN_RATIO || value > MAX_RATIO || value === 1) return null;
  if (!GAP_ACTION_TYPES.includes(actionType as GapActionType)) return null;
  return { kind: "confirm", ratio: value, actionType: actionType as GapActionType };
}

/** "1 股變 4 股" style description of a share ratio (shares after / shares before). */
export function describeShareRatio(ratio: number): string {
  if (ratio >= 1) return `1 股變 ${trim(ratio)} 股（價格 ÷ ${trim(ratio)}）`;
  return `${trim(1 / ratio)} 股併成 1 股（價格 × ${trim(1 / ratio)}）`;
}

function trim(value: number): string {
  return String(Number(value.toFixed(4)));
}
