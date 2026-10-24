import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getIndexChartBars } from "@/lib/markets";
import { CHART_RECENT_MONTHS } from "@/lib/stocks";

/**
 * Daily bars of an index (TAIEX, TPEX) for the K-line chart: all of them, or with
 * ?period=recent the last CHART_RECENT_MONTHS (`complete: false` when older ones exist).
 * Session required.
 */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/markets/[code]/bars">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { code } = await ctx.params;
  const recent = new URL(request.url).searchParams.get("period") === "recent";
  const result = await getIndexChartBars(getDb(), decodeURIComponent(code), recent ? CHART_RECENT_MONTHS : undefined);
  if (!result) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(
    { symbol: code, ...result },
    { headers: { "Cache-Control": "private, max-age=60" } },
  );
}
