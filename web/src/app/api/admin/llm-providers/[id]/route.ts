import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { deleteLlmProvider, updateLlmProvider } from "@/lib/news-admin";
import { parseLlmPatch } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Enable, reorder, change the model or limits, or end a cooldown. Audited. */
export async function PATCH(
  request: Request,
  ctx: RouteContext<"/api/admin/llm-providers/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const patch = parseLlmPatch(await request.json().catch(() => null));
  if (!patch) return Response.json({ error: "設定不正確" }, { status: 400 });
  return respond(await updateLlmProvider(getDb(), id, patch, user.email));
}

/** Remove a service and its usage history. Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/llm-providers/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteLlmProvider(getDb(), id, user.email));
}
