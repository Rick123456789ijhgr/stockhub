import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { createAlias } from "@/lib/news-admin";
import { parseAliasInput } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Add a stock alias used to link news: `{alias, symbol}`. Audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseAliasInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "別名至少 2 個字，代號 4～6 碼" }, { status: 400 });
  return respond(await createAlias(getDb(), input, user.email));
}
