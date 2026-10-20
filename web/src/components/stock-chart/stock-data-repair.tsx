import { TriangleAlert } from "lucide-react";

import { JobButton } from "@/components/jobs/job-button";
import { hasPendingRequest, JobRequestList } from "@/components/jobs/job-request-list";
import { AutoRefresh } from "@/components/status/auto-refresh";
import type { DB } from "@/lib/db";
import { getStockMissingDays, listJobRequests } from "@/lib/job-requests";
import { taipeiToday } from "@/lib/market-hours";
import type { Kysely } from "kysely";

const LOOK_BACK_DAYS = 365;

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/**
 * Days of the past year on which the market traded but this stock has no bar, with a
 * button to re-fetch them (refetch_stock_prices). Hidden when nothing is missing and no
 * repair was asked for recently.
 */
export async function StockDataRepair({
  db,
  stockId,
  symbol,
}: {
  db: Kysely<DB>;
  stockId: number;
  symbol: string;
}) {
  const today = taipeiToday();
  const [missing, requests] = await Promise.all([
    getStockMissingDays(db, String(stockId), shiftDays(today, -LOOK_BACK_DAYS), today),
    listJobRequests(db, { limit: 3, symbol }),
  ]);
  const repairs = requests.filter((r) => r.job === "refetch_stock_prices");
  if (missing.length === 0 && repairs.length === 0) return null;

  return (
    <section aria-labelledby="repair" className="rounded-lg border p-3 text-sm">
      {hasPendingRequest(repairs) ? <AutoRefresh seconds={5} /> : null}
      <h2 id="repair" className="mb-1 flex items-center gap-1.5 font-medium">
        <TriangleAlert className="size-4" aria-hidden />
        {missing.length > 0
          ? `近一年有 ${missing.length} 個交易日沒有這檔的日線`
          : "近一年的日線已完整"}
      </h2>
      {missing.length > 0 ? (
        <>
          <p className="mb-2 text-muted-foreground">
            這些日子市場有開盤，但沒有這一檔的資料（最近：
            <span className="tabular-nums">{missing.slice(-3).join("、")}</span>
            ）。多半是停止交易（例如減資換股）；也可能是當天漏抓，可以重新抓取確認。
          </p>
          <JobButton
            label={`重新抓取${missing.length > 30 ? "最近 30 天" : ""}`}
            requests={[{ job: "refetch_stock_prices", params: { symbol } }]}
          />
        </>
      ) : null}
      <div className="mt-2">
        <JobRequestList rows={repairs} />
      </div>
    </section>
  );
}
