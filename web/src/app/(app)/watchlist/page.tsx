import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { SessionRefresh } from "@/components/session-refresh";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { WatchlistView } from "@/components/watchlist/watchlist-view";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { listWatchlist } from "@/lib/watchlist";

export const metadata: Metadata = { title: "自選" };

export default function WatchlistPage() {
  return (
    <>
      <PageHeader
        title="自選"
        description="盤中每 30 秒更新報價（排程 poll_quotes）；漲跌以參考價為基準。新增、移除、備註、排序都會寫入稽核紀錄。"
      />
      <Card>
        <CardContent>
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <WatchlistContent />
          </Suspense>
        </CardContent>
      </Card>
    </>
  );
}

async function WatchlistContent() {
  await requireUser();
  const items = await listWatchlist(getDb());
  return (
    <>
      {items.some((i) => i.mark?.source === "quote") ? <SessionRefresh /> : null}
      <WatchlistView items={items} />
    </>
  );
}
