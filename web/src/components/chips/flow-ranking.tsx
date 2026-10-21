import type { Kysely } from "kysely";
import Link from "next/link";

import { Disclosure, InfoNote } from "@/components/disclosure";
import { directionClass } from "@/components/price-change";
import { getFlowRanking, getMarketFlows, type MarketFlow, type RankedFlow, type RankingGroup } from "@/lib/chips";
import type { DB } from "@/lib/db";
import { cn } from "@/lib/utils";

const MARKET_LABEL = { twse: "上市", tpex: "上櫃" } as const;
const GROUP_LABEL: Record<RankingGroup, string> = {
  total: "三大法人",
  foreign: "外資",
  trust: "投信",
  dealer: "自營商",
};

function Amount({ value, className }: { value: number | null; className?: string }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const yi = value / 1e8;
  return (
    <span className={cn("tabular-nums", directionClass(yi), className)}>
      {yi > 0 ? "+" : ""}
      {yi.toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
    </span>
  );
}

function MarketTotals({ flows }: { flows: MarketFlow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[22rem] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="text-left font-normal">買賣超（億）</th>
            <th className="text-right font-normal">外資</th>
            <th className="text-right font-normal">投信</th>
            <th className="text-right font-normal">自營商</th>
            <th className="text-right font-normal">合計</th>
          </tr>
        </thead>
        <tbody>
          {flows.map((f) => (
            <tr key={f.market}>
              <td>
                {MARKET_LABEL[f.market]} <span className="text-xs text-muted-foreground tabular-nums">{f.tradeDate.slice(5)}</span>
              </td>
              <td className="text-right">
                <Amount value={f.foreign} />
              </td>
              <td className="text-right">
                <Amount value={f.trust} />
              </td>
              <td className="text-right">
                <Amount value={f.dealer} />
              </td>
              <td className="text-right">
                <Amount value={f.total} className="font-medium" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RankList({ title, rows }: { title: string; rows: RankedFlow[] }) {
  return (
    <div className="min-w-0">
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">—</p>
      ) : (
        <ol className="divide-y text-sm">
          {rows.map((r, i) => (
            <li key={r.symbol} className="flex items-baseline gap-2 py-1">
              <span className="w-4 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{i + 1}</span>
              <Link href={`/stocks/${r.symbol}?tab=chips`} className="min-w-0 flex-1 truncate hover:underline">
                <span className="font-mono text-xs">{r.symbol}</span> {r.name}
              </Link>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                {Math.round(r.netShares / 1000).toLocaleString("zh-TW")} 張
              </span>
              <Amount value={r.netValue} className="w-14 shrink-0 text-right" />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

async function GroupRanking({ db, group }: { db: Kysely<DB>; group: RankingGroup }) {
  const { buys, sells } = await getFlowRanking(db, group);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <RankList title={`${GROUP_LABEL[group]}買超（估計金額，億）`} rows={buys} />
      <RankList title={`${GROUP_LABEL[group]}賣超（估計金額，億）`} rows={sells} />
    </div>
  );
}

/** 首頁「三大法人買賣超排行」: market totals and the day's biggest net buys and sells. */
export async function FlowRanking({ db }: { db: Kysely<DB> }) {
  const [flows, total] = await Promise.all([getMarketFlows(db), getFlowRanking(db, "total")]);
  if (flows.length === 0 && total.tradeDate === null) {
    return <p className="text-sm text-muted-foreground">還沒有三大法人資料（每日 18:00 更新）。</p>;
  }
  return (
    <div className="space-y-4">
      {flows.length > 0 ? <MarketTotals flows={flows} /> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <RankList title="三大法人買超（估計金額，億）" rows={total.buys} />
        <RankList title="三大法人賣超（估計金額，億）" rows={total.sells} />
      </div>
      <Disclosure summary="外資、投信、自營商分開排行">
        <div className="space-y-4 pt-2">
          <GroupRanking db={db} group="foreign" />
          <GroupRanking db={db} group="trust" />
          <GroupRanking db={db} group="dealer" />
        </div>
      </Disclosure>
      <InfoNote>
        {total.tradeDate ? `${total.tradeDate} 的資料。` : ""}
        個股只公布買賣股數，金額以「買賣超股數 × 當日收盤價」估計；全市場金額為交易所公布的實際金額。外資不含外資自營商。
      </InfoNote>
    </div>
  );
}
