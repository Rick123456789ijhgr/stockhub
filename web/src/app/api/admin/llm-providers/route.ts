import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { createLlmProvider } from "@/lib/news-admin";
import { parseLlmCreate } from "@/lib/news-admin-input";
import { respond } from "@/lib/themes";

/** Add an OpenAI-compatible LLM service (its key stays in the environment). Audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseLlmCreate(await request.json().catch(() => null));
  if (!input) return Response.json({ error: "服務設定不正確" }, { status: 400 });
  return respond(await createLlmProvider(getDb(), input, user.email));
}
