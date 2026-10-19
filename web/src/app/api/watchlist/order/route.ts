import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { reorderWatchlist } from "@/lib/watchlist";

/** Save the custom watchlist order (`{symbols: [...]}`); session required; audited. */
export async function PUT(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const body = (await request.json().catch(() => null)) as { symbols?: unknown } | null;
  const symbols = body?.symbols;
  if (!Array.isArray(symbols) || !symbols.every((s) => typeof s === "string") || symbols.length > 1000) {
    return Response.json({ error: "invalid order" }, { status: 400 });
  }
  await reorderWatchlist(getDb(), symbols, user.email);
  return Response.json({ ok: true });
}
