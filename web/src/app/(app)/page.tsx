import Link from "next/link";

import { FlowRanking } from "@/components/chips/flow-ranking";
import { MarketStrip } from "@/components/market/market-strip";
import { PortfolioSummary } from "@/components/portfolio/summary";
import { InfoNote } from "@/components/disclosure";
import { PriceChange } from "@/components/price-change";
import { Section } from "@/components/section";
import { SessionRefresh } from "@/components/session-refresh";
import { Badge } from "@/components/ui/badge";
import { listRecentAlerts } from "@/lib/alerts";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { loadPortfolio } from "@/lib/portfolio-data";

/**
 * Home (D-126): no page title; the session rail above says when the numbers are from. Plain
 * sections instead of a stack of identical cards.
 */
export default function HomePage() {
  return (
    <>
      <h1 className="sr-only">首頁</h1>
      <div className="space-y-10">
        <Section title="持股" actions={<SectionLink href="/portfolio">持股明細</SectionLink>}>
          <Holdings />
        </Section>
        <Section title="大盤與國際市場" actions={<SectionLink href="/market">市場</SectionLink>}>
          <Markets />
        </Section>
        <Section title="警示" actions={<Badge variant="secondary">新聞 M6</Badge>}>
          <InfoNote>
            持股單日漲跌超過近 20 日報酬標準差 × 2.5（最低 3%）時，盤中輪詢與收盤後各檢查一次；外資、投信或自營商單日買賣超達持股成交量
            10%（成交金額 5,000 萬以上）時，抓完籌碼後檢查；景氣燈號變色或 Fed 調整利率時也會提醒。
          </InfoNote>
          <Alerts />
        </Section>
        <Section title="三大法人買賣超">
          <Flows />
        </Section>
      </div>
    </>
  );
}

function SectionLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="underline-offset-4 hover:text-foreground hover:underline">
      {children}
    </Link>
  );
}

async function Holdings() {
  await requireUser();
  const view = await loadPortfolio(getDb());
  if (view.transactions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        還沒有交易紀錄。<Link href="/portfolio#add" className="font-medium text-brand underline-offset-4 hover:underline">新增第一筆交易</Link>
      </p>
    );
  }
  const live = view.ledger.positions.some((p) => p.shares > 0 && view.marks[p.stock]?.source === "quote");
  return (
    <>
      {live ? <SessionRefresh /> : null}
      <PortfolioSummary totals={view.totals} />
    </>
  );
}

async function Markets() {
  await requireUser();
  return <MarketStrip db={getDb()} today={taipeiToday()} />;
}

async function Flows() {
  await requireUser();
  return <FlowRanking db={getDb()} />;
}

async function Alerts() {
  await requireUser();
  const alerts = await listRecentAlerts(getDb());
  if (alerts.length === 0) return <p className="text-sm text-muted-foreground">最近沒有警示。持股大漲大跌或法人大量買賣時會列在這裡。</p>;
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
