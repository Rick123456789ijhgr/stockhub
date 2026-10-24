import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { deleteAlias } from "@/lib/news-admin";
import { respond } from "@/lib/themes";

/** Remove a stock alias. Audited. */
export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/admin/aliases/[alias]">,
): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const alias = decodeURIComponent((await ctx.params).alias).trim();
  if (!alias || alias.length > 20) return Response.json({ error: "not found" }, { status: 404 });
  return respond(await deleteAlias(getDb(), alias, user.email));
}
