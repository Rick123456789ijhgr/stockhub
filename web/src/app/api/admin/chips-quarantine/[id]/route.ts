import { requireApiUser } from "@/lib/auth/session";
import { resolveQuarantinedChip } from "@/lib/chips-quarantine";
import { getDb } from "@/lib/db";

/** Review a quarantined chip row: `{decision: "accept" | "reject"}`. Session required; audited. */
export async function POST(
  request: Request,
  ctx: RouteContext<"/api/admin/chips-quarantine/[id]">,
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
  const done = await resolveQuarantinedChip(getDb(), id, decision, user.email);
  if (!done) return Response.json({ error: "not found or already reviewed" }, { status: 409 });
  return Response.json({ ok: true });
}
