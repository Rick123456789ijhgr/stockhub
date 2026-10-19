import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { setWatched } from "@/lib/quotes";
import { findStock } from "@/lib/stocks";

type Ctx = RouteContext<"/api/watchlist/[symbol]">;

async function update(ctx: Ctx, watched: boolean): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { symbol } = await ctx.params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock || stock.delistedDate) {
    return Response.json({ error: "not found" }, { status: 404 });
  }
  await setWatched(db, stock, watched, user.email);
  return Response.json({ watched });
}

/** Add a stock to the watchlist (idempotent); session required. */
export async function PUT(_request: Request, ctx: Ctx): Promise<Response> {
  return update(ctx, true);
}

/** Remove a stock from the watchlist (idempotent); session required. */
export async function DELETE(_request: Request, ctx: Ctx): Promise<Response> {
  return update(ctx, false);
}
