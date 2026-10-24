import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { deleteSlang, updateSlang } from "@/lib/news-admin";
import { parseSlangInput } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Change a slang term. Audited. */
export async function PATCH(
  request: Request,
  ctx: RouteContext<"/api/admin/slang/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const input = parseSlangInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "詞條不正確" }, { status: 400 });
  return respond(await updateSlang(getDb(), id, input, user.email));
}

/** Remove a slang term. Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/slang/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteSlang(getDb(), id, user.email));
}
