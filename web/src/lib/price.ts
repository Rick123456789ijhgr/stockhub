/** Close-to-close change; null when either side is missing. */
export function priceChange(
  close: string | null,
  prevClose: string | null,
): { change: number; percent: number } | null {
  if (close === null || prevClose === null) return null;
  const c = Number(close);
  const p = Number(prevClose);
  if (!Number.isFinite(c) || !Number.isFinite(p) || p === 0) return null;
  return { change: c - p, percent: ((c - p) / p) * 100 };
}
