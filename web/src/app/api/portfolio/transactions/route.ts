import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { applyTransactionChange } from "@/lib/portfolio-data";
import { parseTransactionInput } from "@/lib/transaction-input";

/** Record a trade (fee and tax filled in unless given); session required; audited. */
export async function POST(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const parsed = parseTransactionInput(await request.json().catch(() => null), taipeiToday());
  if (!parsed.ok) return Response.json({ error: parsed.error }, { status: 400 });
  const result = await applyTransactionChange(getDb(), { kind: "create", input: parsed.value }, user.email);
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ id: result.id }, { status: 201 });
}
