import type { Kysely } from "kysely";

import { InfoNote } from "@/components/disclosure";
import { getFlowRanking, getMarketFlows, type RankingGroup } from "@/lib/chips";
import type { DB } from "@/lib/db";

import { FlowBoard, type GroupRankings } from "./flow-board";

const GROUPS: RankingGroup[] = ["total", "foreign", "trust", "dealer"];

/**
 * 首頁「三大法人買賣超」(D-130): market totals as diverging bars per market, and the day's
 * biggest net buys and sells as a butterfly chart. All four groups load here (8 small
 * queries on one day), so switching groups needs no round trip.
 */
export async function FlowRanking({ db }: { db: Kysely<DB> }) {
  const [flows, ...rankings] = await Promise.all([
    getMarketFlows(db),
    ...GROUPS.map((group) => getFlowRanking(db, group)),
  ]);
  const tradeDate = rankings[0]?.tradeDate ?? null;
  if (flows.length === 0 && tradeDate === null) {
    return <p className="text-sm text-muted-foreground">還沒有三大法人資料（每日 18:00 更新）。</p>;
  }
  const byGroup = Object.fromEntries(
    GROUPS.map((group, i) => [group, { buys: rankings[i]!.buys, sells: rankings[i]!.sells }]),
  ) as GroupRankings;
  return (
    <div className="space-y-4">
      <FlowBoard flows={flows} rankings={byGroup} tradeDate={tradeDate} />
      <InfoNote>
        個股只公布買賣股數，金額以「買賣超股數 × 當日收盤價」估計；全市場金額為交易所公布的實際金額。外資不含外資自營商。滑過個股可看張數與收盤價。
      </InfoNote>
    </div>
  );
}
