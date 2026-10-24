import type { Kysely } from "kysely";

import { InfoNote } from "@/components/disclosure";
import { Card, CardContent } from "@/components/ui/card";
import type { DB } from "@/lib/db";
import type { SeriesCategory } from "@/lib/market-series";
import { loadSeries, shiftDate } from "@/lib/markets";

import { SeriesCard } from "./series-card";

const SECTIONS: { title: string; categories: SeriesCategory[] }[] = [
  { title: "國際股市", categories: ["intl_index", "volatility"] },
  { title: "匯率與商品", categories: ["fx", "commodity"] },
  { title: "利率", categories: ["rate"] },
];

/**
 * 國際市場: every daily international series with its latest value and one year of history.
 * Taiwan's indexes are on the home page.
 */
export async function MarketOverview({ db, today }: { db: Kysely<DB>; today: string }) {
  const all = await loadSeries(db, shiftDate(today, -370));
  const daily = all.filter((s) => s.frequency === "daily");
  if (!daily.some((s) => s.points.length)) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">
          還沒有市場資料：執行 <code>make etl-markets</code>（歷史用 <code>make etl-markets-history</code>）。
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-5">
      <InfoNote>
        國際指數、匯率、黃金與原油期貨、VIX 主要來自 Yahoo
        Finance（非官方，失敗時改用 FRED），美債殖利率與 Fed 利率來自
        FRED。日期是各交易所的當地日期，所以美股的「10/20」是台灣 10/21
        早上收盤的那一天。紅漲綠跌只用在指數與商品；匯率、波動率、利率以中性色顯示變動。
      </InfoNote>
      {SECTIONS.map((section) => {
        const items = daily.filter((s) => section.categories.includes(s.category));
        if (!items.length) return null;
        return (
          <section key={section.title} aria-labelledby={`market-${section.title}`} className="space-y-2">
            <h2 id={`market-${section.title}`} className="text-sm font-medium text-muted-foreground">
              {section.title}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((s) => (
                <SeriesCard key={s.code} series={s} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
