import { requireApiUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { applyReceiptChange } from "@/lib/portfolio-data";
import { isIsoDate } from "@/lib/transaction-input";
import { parseReceiptInput } from "@/lib/receipt-input";

/** Record what actually arrived for an estimated dividend; session required; audited. */
export async function PUT(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const parsed = parseReceiptInput(await request.json().catch(() => null));
  if (!parsed.ok) return Response.json({ error: parsed.error }, { status: 400 });
  const result = await applyReceiptChange(getDb(), { kind: "save", input: parsed.value }, user.email);
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ ok: true });
}

/** Go back to the estimate (`?symbol=&exDate=&actionType=`); session required; audited. */
export async function DELETE(request: Request): Promise<Response> {
  const user = await requireApiUser();
  if (user instanceof Response) return user;
  const params = new URL(request.url).searchParams;
  const symbol = (params.get("symbol") ?? "").toUpperCase();
  const exDate = params.get("exDate");
  const actionType = params.get("actionType") ?? "";
  if (!/^[0-9A-Z]{4,6}$/.test(symbol) || !isIsoDate(exDate) || !/^[a-z_]{3,40}$/.test(actionType)) {
    return Response.json({ error: "invalid event" }, { status: 400 });
  }
  const result = await applyReceiptChange(
    getDb(),
    { kind: "clear", symbol, exDate, actionType },
    user.email,
  );
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ ok: true });
}
