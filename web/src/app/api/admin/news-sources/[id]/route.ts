import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { deleteSource, updateSource } from "@/lib/news-admin";
import { parseSourcePatch } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Enable, rename, re-time or filter a source. Audited. */
export async function PATCH(
  request: Request,
  ctx: RouteContext<"/api/admin/news-sources/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const patch = parseSourcePatch(await request.json().catch(() => null));
  if (!patch) return Response.json({ error: "設定不正確" }, { status: 400 });
  return respond(await updateSource(getDb(), id, patch, user.email));
}

/** Remove an RSS feed and its items (built-in sources can only be disabled). Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/news-sources/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteSource(getDb(), id, user.email));
}
