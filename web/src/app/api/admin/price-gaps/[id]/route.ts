import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseGapDecision } from "@/lib/price-gap-decision";
import { resolveGap } from "@/lib/price-gaps";

/**
 * Review a price-gap flag: `{decision: "confirm", ratio, actionType}` records the event,
 * `{decision: "dismiss"}` marks it a real price move. Session required; audited.
 */
export async function POST(
  request: Request,
  ctx: RouteContext<"/api/admin/price-gaps/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const decision = parseGapDecision(await request.json().catch(() => null));
  if (!decision) return Response.json({ error: "invalid decision" }, { status: 400 });
  const done = await resolveGap(getDb(), id, decision, user.email);
  if (!done) return Response.json({ error: "not found or already reviewed" }, { status: 409 });
  return Response.json({ ok: true });
}
