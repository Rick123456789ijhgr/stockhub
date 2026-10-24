import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { createSlang } from "@/lib/news-admin";
import { parseSlangInput } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Add a slang term: `{term, meaning, polarity?}`. Audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseSlangInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "詞條不正確" }, { status: 400 });
  return respond(await createSlang(getDb(), input, user.email));
}
