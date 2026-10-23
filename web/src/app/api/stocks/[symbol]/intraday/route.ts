import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getIntraday } from "@/lib/quotes";
import { findStock } from "@/lib/stocks";

/** The latest sampled day of a stock's intraday quotes; session required. */
export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]/intraday">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  const day = await getIntraday(db, stock.id);
  return Response.json({ day }, { headers: { "Cache-Control": "no-store" } });
}
