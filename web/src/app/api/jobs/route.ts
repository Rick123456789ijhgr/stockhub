import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { parseJobRequest } from "@/lib/job-request-input";
import { enqueueJob, listJobRequests } from "@/lib/job-requests";
import { startDrainer } from "@/lib/job-runner";
import { taipeiToday } from "@/lib/market-hours";

/**
 * Queue a data job from the site: `{job, params}` (see lib/job-request-input.ts).
 * 202 with `runner: "started"` when it starts right away (local), `"queued"` when it waits
 * for the next scheduled run. Session required; audited as jobs.request.
 */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const input = parseJobRequest(await request.json().catch(() => null), taipeiToday());
  if (!input) return Response.json({ error: "invalid job request" }, { status: 400 });
  const { id, duplicate } = await enqueueJob(getDb(), input, user.email);
  const runner = startDrainer();
  return Response.json({ id, duplicate, runner }, { status: 202 });
}

/** Recent requests (newest first); `?symbol=` narrows to one stock. */
export async function GET(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const symbol = new URL(request.url).searchParams.get("symbol") ?? undefined;
  const requests = await listJobRequests(getDb(), { limit: 10, symbol });
  return Response.json({ requests });
}
