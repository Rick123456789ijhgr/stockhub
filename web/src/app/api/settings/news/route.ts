import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getNewsSettings, saveNewsSettings } from "@/lib/news-admin";
import { parseNewsSettings } from "@/lib/news-admin-input";

/** Current news settings (defaults when never saved); session required. */
export async function GET(): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  return Response.json(await getNewsSettings(getDb()));
}

/** Replace the news settings (LLM caps, alert thresholds); session required; audited. */
export async function PUT(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const settings = parseNewsSettings(await request.json().catch(() => null));
  if (!settings) return Response.json({ error: "設定超出範圍" }, { status: 400 });
  await saveNewsSettings(getDb(), settings, user.email);
  return Response.json(settings);
}
