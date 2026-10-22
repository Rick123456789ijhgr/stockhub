import { requireApiUser } from "@/lib/auth/session";
import { reviewResponse } from "@/lib/constraint-error";
import { getDb } from "@/lib/db";
import { resolveQuarantinedObservation } from "@/lib/series-quarantine";

/** Review a quarantined market series value: `{decision: "accept" | "reject"}`. Audited. */
export async function POST(
  request: Request,
  ctx: RouteContext<"/api/admin/series-quarantine/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const body = (await request.json().catch(() => null)) as { decision?: unknown } | null;
  const decision = body?.decision;
  if (decision !== "accept" && decision !== "reject") {
    return Response.json({ error: "invalid decision" }, { status: 400 });
  }
  return reviewResponse(() => resolveQuarantinedObservation(getDb(), id, decision, user.email));
}
