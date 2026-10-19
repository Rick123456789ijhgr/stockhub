import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { loadMarks } from "@/lib/portfolio-data";
import { findStock } from "@/lib/stocks";

/** Name, type and latest price of a stock, for the trade form; session required. */
export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/stocks/[symbol]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol).trim().toUpperCase());
  if (!stock) return Response.json({ error: "not found" }, { status: 404 });
  const mark = (await loadMarks(db, [String(stock.id)]))[String(stock.id)] ?? null;
  return Response.json(
    {
      symbol: stock.symbol,
      name: stock.name,
      type: stock.type,
      delistedDate: stock.delistedDate,
      price: mark?.price ?? null,
      priceDate: mark?.date ?? null,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
