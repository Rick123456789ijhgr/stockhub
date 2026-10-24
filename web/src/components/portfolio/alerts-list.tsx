import type { Kysely } from "kysely";
import Link from "next/link";

import { PriceChange } from "@/components/price-change";
import { listRecentAlerts } from "@/lib/alerts";
import type { DB } from "@/lib/db";

/** Recent alerts (holding moves, institutional trades, macro), newest first. */
export async function AlertsList({ db }: { db: Kysely<DB> }) {
  const alerts = await listRecentAlerts(db);
  if (alerts.length === 0) {
    return <p className="text-sm text-muted-foreground">最近沒有警示。持股大漲大跌或法人大量買賣時會列在這裡。</p>;
  }
  return (
    <ul className="divide-y text-sm">
      {alerts.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
          <Link href={a.symbol ? `/stocks/${a.symbol}` : "/market?tab=macro"} className="font-medium hover:underline">
            {a.title}
          </Link>
          <span className="text-xs text-muted-foreground tabular-nums">
            {a.tradeDate}
            {a.change !== null ? (
              <>
                {" "}
                <PriceChange value={a.change * 100} suffix="%" />
              </>
            ) : null}
            {a.kind === "holding_move" && a.threshold !== null ? `（門檻 ±${(a.threshold * 100).toFixed(1)}%）` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
