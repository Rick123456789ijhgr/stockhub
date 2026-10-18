import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { findStock, getChartBars } from "@/lib/stocks";

/** Every traded daily bar of a stock for the K-line chart; session required. */
export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]/bars">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(
    { symbol: stock.symbol, bars: await getChartBars(db, stock.id) },
    { headers: { "Cache-Control": "private, max-age=60" } },
  );
}
