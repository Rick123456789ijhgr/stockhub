import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseFeeSettings } from "@/lib/fee-settings";
import { getFeeSettings, saveFeeSettings } from "@/lib/settings";

/** Current fee settings (defaults when never saved); session required. */
export async function GET(): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  return Response.json(await getFeeSettings(getDb()));
}

/** Replace the fee settings; session required; audited. */
export async function PUT(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const settings = parseFeeSettings(await request.json().catch(() => null));
  if (!settings) return Response.json({ error: "invalid settings" }, { status: 400 });
  await saveFeeSettings(getDb(), settings, user.email);
  return Response.json(settings);
}
