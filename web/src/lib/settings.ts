import "server-only";

import type { Kysely } from "kysely";

import type { DB } from "@/lib/db";
import { feeSettingsFromStored } from "@/lib/fee-settings";
import type { FeeSettings } from "@/lib/portfolio";

const FEES_KEY = "fees";

/** Fee settings from `settings` (key `fees`), or the defaults when never saved. */
export async function getFeeSettings(db: Kysely<DB>): Promise<FeeSettings> {
  const row = await db
    .selectFrom("settings")
    .select("value")
    .where("key", "=", FEES_KEY)
    .executeTakeFirst();
  return feeSettingsFromStored(row?.value);
}

/** Save fee settings and audit the change (no-op when nothing changed). */
export async function saveFeeSettings(
  db: Kysely<DB>,
  next: FeeSettings,
  actor: string,
): Promise<void> {
  await db.transaction().execute(async (trx) => {
    const before = await getFeeSettings(trx);
    if (JSON.stringify(before) === JSON.stringify(next)) return;
    const value = JSON.stringify(next);
    await trx
      .insertInto("settings")
      .values({ key: FEES_KEY, value })
      .onConflict((oc) => oc.column("key").doUpdateSet({ value }))
      .execute();
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: "settings.fees",
        target: FEES_KEY,
        detail: JSON.stringify({ before, after: next }),
      })
      .execute();
  });
}
