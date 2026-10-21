import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseThemeInput } from "@/lib/theme-input";
import { deleteTheme, updateTheme, respond } from "@/lib/themes";

/** Rename a theme or change its description: `{name, description?}`. Audited. */
export async function PATCH(
  request: Request,
  ctx: RouteContext<"/api/admin/themes/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  const input = parseThemeInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "invalid theme" }, { status: 400 });
  return respond(await updateTheme(getDb(), id, input, user.email));
}

/** Delete a theme and its memberships. Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/themes/[id]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteTheme(getDb(), id, user.email));
}
