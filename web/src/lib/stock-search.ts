/** Search text helpers for lib/stocks.ts (pure, so they can be tested). */

/** The search text as typed on any keyboard: full-width digits and letters (８７８) become
 * ASCII, spaces at the ends go. */
export function normalizeQuery(query: string): string {
  return query.normalize("NFKC").trim();
}

/** `text` for a LIKE pattern, with its wildcards (% _ and the escape \) taken literally. */
export function escapeLike(text: string): string {
  return text.replace(/[\\%_]/g, (c) => `\\${c}`);
}
