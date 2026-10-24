import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { createSource } from "@/lib/news-admin";
import { parseSourceCreate } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Add an RSS feed: `{name, url, intervalMinutes?, keywords?, useLlm?}`. Audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseSourceCreate(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "網址或設定不正確" }, { status: 400 });
  return respond(await createSource(getDb(), input, user.email));
}
