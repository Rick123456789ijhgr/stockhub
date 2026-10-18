import "server-only";

import { Kysely, PostgresDialect } from "kysely";
import pg from "pg";

import type { DB } from "./types.gen";

// Trading dates stay "YYYY-MM-DD" strings (matches kysely-codegen dateParser: "string");
// converting them to JS Date would shift them by the server's time zone.
pg.types.setTypeParser(pg.types.builtins.DATE, (value) => value);

const globalForDb = globalThis as unknown as { stockhubDb?: Kysely<DB> };

/** Shared Kysely instance (one pool per server process, reused across dev reloads). */
export function getDb(): Kysely<DB> {
  if (!globalForDb.stockhubDb) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) throw new Error("DATABASE_URL is not set (see .env.example)");
    globalForDb.stockhubDb = new Kysely<DB>({
      dialect: new PostgresDialect({ pool: new pg.Pool({ connectionString, max: 5 }) }),
    });
  }
  return globalForDb.stockhubDb;
}

export type { DB };
