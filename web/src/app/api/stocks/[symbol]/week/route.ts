import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getLatestQuote } from "@/lib/quotes";
import { findStock, getRecentBars, MARKET_LABEL } from "@/lib/stocks";
import { PREVIEW_DAYS, weekPreview } from "@/lib/week-preview";

/** Five-day candles for the stock hover preview (D-132); session required. */
export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]/week">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  // A few spare rows so days without trades still leave five candles and a base.
  const [bars, quote] = await Promise.all([getRecentBars(db, stock.id, PREVIEW_DAYS + 4), getLatestQuote(db, stock.id)]);
  return Response.json(
    {
      symbol: stock.symbol,
      name: stock.name,
      market: MARKET_LABEL[stock.market],
      isEtf: stock.type === "etf",
      ...weekPreview(bars, quote),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
