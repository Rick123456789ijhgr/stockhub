import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getLatestQuote, isWatched } from "@/lib/quotes";
import { findStock } from "@/lib/stocks";

/** Latest intraday snapshot and watchlist state of a stock; session required. */
export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]/quote">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  const [quote, watched] = await Promise.all([
    getLatestQuote(db, stock.id),
    isWatched(db, stock.id),
  ]);
  return Response.json({ quote, watched }, { headers: { "Cache-Control": "no-store" } });
}
