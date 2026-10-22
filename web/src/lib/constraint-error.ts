/**
 * A row that failed quality checks can also break a table constraint (e.g. a foreign
 * holding ratio above 100%), so "accept" cannot store it. The review routes turn those
 * PostgreSQL errors into a message the page shows instead of a bare failure.
 */

const MESSAGES: Record<string, string> = {
  "23514": "這筆資料超出資料表允許的範圍（例如比率大於 100%、最高價低於最低價），無法採用，只能捨棄。",
  "23502": "這筆資料缺少必要欄位，無法採用，只能捨棄。",
  "22003": "這筆資料的數值超出欄位範圍，無法採用，只能捨棄。",
};

export function constraintMessage(error: unknown): string | null {
  const code = typeof error === "object" && error !== null ? (error as { code?: unknown }).code : undefined;
  return typeof code === "string" ? (MESSAGES[code] ?? null) : null;
}

/** Run a review action; a constraint violation becomes a 409 with the message above. */
export async function reviewResponse(action: () => Promise<boolean>): Promise<Response> {
  try {
    const done = await action();
    if (!done) return Response.json({ error: "找不到這筆資料，或已經處理過" }, { status: 409 });
    return Response.json({ ok: true });
  } catch (error) {
    const message = constraintMessage(error);
    if (message === null) throw error;
    return Response.json({ error: message }, { status: 409 });
  }
}
