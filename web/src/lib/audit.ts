import "server-only";

import type { Kysely } from "kysely";

import type { DB } from "@/lib/db";

export type AuditEntry = {
  id: string;
  at: string;
  actor: string;
  action: string;
  target: string | null;
  detail: unknown;
};

/** Newest-first audit log page; `before` is the id of the last entry of the previous page. */
export async function listAuditLog(
  db: Kysely<DB>,
  { limit = 50, before }: { limit?: number; before?: string } = {},
): Promise<AuditEntry[]> {
  let query = db
    .selectFrom("audit_log")
    .select(["id", "at", "actor", "action", "target", "detail"])
    .orderBy("id", "desc")
    .limit(Math.min(Math.max(limit, 1), 200));
  if (before) query = query.where("id", "<", before);
  const rows = await query.execute();
  return rows.map((r) => ({ ...r, id: String(r.id), at: r.at.toISOString() }));
}
