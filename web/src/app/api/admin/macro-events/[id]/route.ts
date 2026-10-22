import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { deleteMacroEvent, respond } from "@/lib/themes";

/** Delete a calendar event (seeded and recorded ones too). Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/macro-events/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteMacroEvent(getDb(), id, user.email));
}
