import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseThemeInput } from "@/lib/theme-input";
import { createTheme, respond } from "@/lib/themes";

/** Create a theme: `{name, description?}`. Session required; audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseThemeInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "invalid theme" }, { status: 400 });
  return respond(await createTheme(getDb(), input, user.email));
}
