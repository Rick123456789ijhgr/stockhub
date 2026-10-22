import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { parseMemberInput, parseMemberKey } from "@/lib/theme-input";
import { addMember, changeMember, respond } from "@/lib/themes";

type Ctx = RouteContext<"/api/admin/themes/[id]/members">;

async function themeId(ctx: Ctx): Promise<string | null> {
  const { id } = await ctx.params;
  return /^\d+$/.test(id) ? id : null;
}

/** Add a stock to a theme: `{symbol, validFrom?, note?}` (validFrom defaults to today). Audited. */
export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const id = await themeId(ctx);
  if (!id) return Response.json({ error: "not found" }, { status: 404 });
  const input = parseMemberInput(await request.json().catch(() => null), taipeiToday());
  if (!input) return Response.json({ error: "invalid member" }, { status: 400 });
  return respond(await addMember(getDb(), id, input, user.email));
}

/** End a membership: `{stockId, validFrom, validTo}`. Audited. */
export async function PATCH(request: Request, ctx: Ctx): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const id = await themeId(ctx);
  if (!id) return Response.json({ error: "not found" }, { status: 404 });
  const key = parseMemberKey(await request.json().catch(() => null), true);
  if (!key) return Response.json({ error: "invalid member" }, { status: 400 });
  return respond(await changeMember(getDb(), id, key, user.email));
}

/** Delete a membership period entered by mistake: `{stockId, validFrom}`. Audited. */
export async function DELETE(request: Request, ctx: Ctx): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const id = await themeId(ctx);
  if (!id) return Response.json({ error: "not found" }, { status: 404 });
  const key = parseMemberKey(await request.json().catch(() => null), false);
  if (!key) return Response.json({ error: "invalid member" }, { status: 400 });
  return respond(await changeMember(getDb(), id, key, user.email));
}
