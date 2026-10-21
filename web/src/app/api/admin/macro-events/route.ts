import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseEventInput } from "@/lib/theme-input";
import { createMacroEvent, respond } from "@/lib/themes";

/** Add a calendar event: `{date, kind, title, note?}`. Session required; audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseEventInput(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "invalid event" }, { status: 400 });
  return respond(await createMacroEvent(getDb(), input, user.email));
}
