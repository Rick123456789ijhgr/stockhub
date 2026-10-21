import "server-only";

import { type Kysely, sql, type Transaction } from "kysely";

import type { DB } from "@/lib/db";
import {
  type EventInput,
  type MemberInput,
  type MemberKey,
  overlaps,
  type ThemeInput,
} from "@/lib/theme-input";

export type ThemeMember = {
  stockId: string;
  symbol: string;
  name: string;
  validFrom: string;
  validTo: string | null;
  note: string | null;
};

export type Theme = { id: string; name: string; description: string | null; members: ThemeMember[] };

/** Every theme with its membership periods (current first, then ended), by name. */
export async function listThemes(db: Kysely<DB>): Promise<Theme[]> {
  const [themes, members] = await Promise.all([
    db.selectFrom("themes").select(["id", "name", "description"]).orderBy("name").execute(),
    db
      .selectFrom("stock_themes as st")
      .innerJoin("stocks as s", "s.id", "st.stock_id")
      .select(["st.theme_id", "st.stock_id", "s.symbol", "s.name", "st.valid_from", "st.valid_to", "st.note"])
      .orderBy(sql`st.valid_to IS NULL`, "desc")
      .orderBy("s.symbol")
      .execute(),
  ]);
  const by = new Map<string, ThemeMember[]>();
  for (const m of members) {
    const list = by.get(String(m.theme_id)) ?? [];
    list.push({
      stockId: String(m.stock_id),
      symbol: m.symbol,
      name: m.name,
      validFrom: String(m.valid_from),
      validTo: m.valid_to === null ? null : String(m.valid_to),
      note: m.note,
    });
    by.set(String(m.theme_id), list);
  }
  return themes.map((t) => ({
    id: String(t.id),
    name: t.name,
    description: t.description,
    members: by.get(String(t.id)) ?? [],
  }));
}

export type Result = { ok: true } | { ok: false; status: number; error: string };
const fail = (status: number, error: string): Result => ({ ok: false, status, error });

/** The JSON response of a Result for the admin route handlers. */
export function respond(result: Result): Response {
  return result.ok
    ? Response.json({ ok: true })
    : Response.json({ error: result.error }, { status: result.status });
}

async function audit(trx: Transaction<DB>, actor: string, action: string, target: string, detail: unknown) {
  await trx
    .insertInto("audit_log")
    .values({ actor, action, target, detail: JSON.stringify(detail) })
    .execute();
}

async function themeName(trx: Transaction<DB>, id: string): Promise<string | null> {
  const row = await trx
    .selectFrom("themes")
    .select("name")
    .where("id", "=", id)
    .forUpdate()
    .executeTakeFirst();
  return row?.name ?? null;
}

export async function createTheme(db: Kysely<DB>, input: ThemeInput, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .insertInto("themes")
      .values(input)
      .onConflict((oc) => oc.column("name").doNothing())
      .returning("id")
      .executeTakeFirst();
    if (!row) return fail(409, "已有同名題材");
    await audit(trx, actor, "theme.create", input.name, { themeId: String(row.id), ...input });
    return { ok: true } as const;
  });
}

export async function updateTheme(
  db: Kysely<DB>,
  id: string,
  input: ThemeInput,
  actor: string,
): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const before = await themeName(trx, id);
    if (before === null) return fail(404, "找不到題材");
    const clash = await trx
      .selectFrom("themes")
      .select("id")
      .where("name", "=", input.name)
      .where("id", "<>", id)
      .executeTakeFirst();
    if (clash) return fail(409, "已有同名題材");
    await trx.updateTable("themes").set(input).where("id", "=", id).execute();
    await audit(trx, actor, "theme.update", input.name, { themeId: id, before, ...input });
    return { ok: true } as const;
  });
}

export async function deleteTheme(db: Kysely<DB>, id: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const name = await themeName(trx, id);
    if (name === null) return fail(404, "找不到題材");
    const members = await trx
      .selectFrom("stock_themes")
      .select(sql<number>`count(*)::int`.as("n"))
      .where("theme_id", "=", id)
      .executeTakeFirstOrThrow();
    await trx.deleteFrom("themes").where("id", "=", id).execute();
    await audit(trx, actor, "theme.delete", name, { themeId: id, members: members.n });
    return { ok: true } as const;
  });
}

export async function addMember(
  db: Kysely<DB>,
  themeId: string,
  input: MemberInput,
  actor: string,
): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const name = await themeName(trx, themeId);
    if (name === null) return fail(404, "找不到題材");
    const stock = await trx
      .selectFrom("stocks")
      .select(["id", "symbol"])
      .where("symbol", "=", input.symbol)
      .orderBy(sql`delisted_date IS NULL`, "desc")
      .orderBy("listed_date", "desc")
      .executeTakeFirst();
    if (!stock) return fail(404, `找不到股票 ${input.symbol}`);
    const periods = await trx
      .selectFrom("stock_themes")
      .select(["valid_from", "valid_to"])
      .where("theme_id", "=", themeId)
      .where("stock_id", "=", stock.id)
      .execute();
    const existing = periods.map((p) => ({
      validFrom: String(p.valid_from),
      validTo: p.valid_to === null ? null : String(p.valid_to),
    }));
    if (overlaps(existing, input.validFrom)) return fail(409, `${input.symbol} 在這段期間已經是成分股`);
    await trx
      .insertInto("stock_themes")
      .values({ theme_id: themeId, stock_id: stock.id, valid_from: input.validFrom, note: input.note })
      .execute();
    await audit(trx, actor, "theme.add_stock", input.symbol, {
      themeId,
      theme: name,
      validFrom: input.validFrom,
    });
    return { ok: true } as const;
  });
}

/** Set the last day of a membership (`validTo`), or delete the period when `validTo` is absent. */
export async function changeMember(
  db: Kysely<DB>,
  themeId: string,
  key: MemberKey,
  actor: string,
): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const name = await themeName(trx, themeId);
    if (name === null) return fail(404, "找不到題材");
    const row = await trx
      .selectFrom("stock_themes as st")
      .innerJoin("stocks as s", "s.id", "st.stock_id")
      .select("s.symbol")
      .where("st.theme_id", "=", themeId)
      .where("st.stock_id", "=", key.stockId)
      .where("st.valid_from", "=", key.validFrom)
      .executeTakeFirst();
    if (!row) return fail(404, "找不到這段成分股期間");
    const scope = { theme_id: themeId, stock_id: key.stockId, valid_from: key.validFrom };
    if (key.validTo) {
      await trx
        .updateTable("stock_themes")
        .set({ valid_to: key.validTo })
        .where("theme_id", "=", scope.theme_id)
        .where("stock_id", "=", scope.stock_id)
        .where("valid_from", "=", scope.valid_from)
        .execute();
      await audit(trx, actor, "theme.end_stock", row.symbol, { themeId, theme: name, ...key });
    } else {
      await trx
        .deleteFrom("stock_themes")
        .where("theme_id", "=", scope.theme_id)
        .where("stock_id", "=", scope.stock_id)
        .where("valid_from", "=", scope.valid_from)
        .execute();
      await audit(trx, actor, "theme.remove_stock", row.symbol, { themeId, theme: name, ...key });
    }
    return { ok: true } as const;
  });
}

export async function createMacroEvent(db: Kysely<DB>, input: EventInput, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .insertInto("macro_events")
      .values({
        event_date: input.date,
        kind: input.kind,
        title: input.title,
        note: input.note,
        source: "manual",
      })
      .onConflict((oc) => oc.constraint("macro_events_natural_key").doNothing())
      .returning("id")
      .executeTakeFirst();
    if (!row) return fail(409, "同一天已有相同事件");
    await audit(trx, actor, "macro_event.create", input.title, { eventId: String(row.id), ...input });
    return { ok: true } as const;
  });
}

export async function deleteMacroEvent(db: Kysely<DB>, id: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .deleteFrom("macro_events")
      .where("id", "=", id)
      .returning(["event_date", "kind", "title", "source"])
      .executeTakeFirst();
    if (!row) return fail(404, "找不到事件");
    await audit(trx, actor, "macro_event.delete", row.title, {
      eventId: id,
      date: String(row.event_date),
      kind: row.kind,
      source: row.source,
    });
    return { ok: true } as const;
  });
}
