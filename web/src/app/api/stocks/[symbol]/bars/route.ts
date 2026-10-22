import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { CHART_RECENT_MONTHS, findStock, getChartBars } from "@/lib/stocks";

/**
 * Traded daily bars of a stock for the K-line chart: all of them, or with ?period=recent
 * the last CHART_RECENT_MONTHS (`complete: false` when older ones exist). Session required.
 */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]/bars">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  const recent = new URL(request.url).searchParams.get("period") === "recent";
  const { bars, complete } = await getChartBars(db, stock.id, recent ? CHART_RECENT_MONTHS : undefined);
  return Response.json(
    { symbol: stock.symbol, bars, complete },
    { headers: { "Cache-Control": "private, max-age=60" } },
  );
}
