import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { applyTransactionChange, type TransactionChange } from "@/lib/portfolio-data";
import { parseTransactionInput } from "@/lib/transaction-input";

type Ctx = RouteContext<"/api/portfolio/transactions/[id]">;

async function change(ctx: Ctx, build: (id: string) => Promise<TransactionChange | Response>) {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "找不到這筆交易" }, { status: 404 });
  const built = await build(id);
  if (built instanceof Response) return built;
  const result = await applyTransactionChange(getDb(), built, user.email);
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ id: result.id });
}

/** Replace a trade; session required; audited. */
export async function PATCH(request: Request, ctx: Ctx): Promise<Response> {
  return change(ctx, async (id) => {
    const parsed = parseTransactionInput(await request.json().catch(() => null), taipeiToday());
    if (!parsed.ok) return Response.json({ error: parsed.error }, { status: 400 });
    return { kind: "update", id, input: parsed.value };
  });
}

/** Delete a trade (refused if a later sell would exceed the holding); audited. */
export async function DELETE(_request: Request, ctx: Ctx): Promise<Response> {
  return change(ctx, async (id) => ({ kind: "delete", id }));
}
