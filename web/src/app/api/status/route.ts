import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getStatusData } from "@/lib/status";

/** JSON variant of /status (for client-side refresh); session required. */
export async function GET(): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  return Response.json(await getStatusData(getDb()));
}
