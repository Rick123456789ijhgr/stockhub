import type { Kysely } from "kysely";

import { type ChartSeries, TimeChart } from "@/components/charts/time-chart";
import { InfoNote } from "@/components/disclosure";
import { ShowMoreRows } from "@/components/show-more";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DB } from "@/lib/db";
import { percentToFraction, type SeriesPoint, spread, yearOverYear } from "@/lib/market-series";
import { EVENT_KIND_LABEL, listMacroEvents, loadSeries, type LoadedSeries, shiftDate } from "@/lib/markets";

const line = (
  name: string,
  points: readonly SeriesPoint[],
  color: ChartSeries["color"] = "--series-1",
): ChartSeries => ({
  name,
  kind: "line",
  color,
  width: 2,
  data: points.map((p) => ({ time: p.date, value: p.value })),
});

function ChartCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** 總經: NDC light and indicators, US rates and inflation, and the event calendar. */
export async function MacroSection({ db, today }: { db: Kysely<DB>; today: string }) {
  const [monthly, rates, events] = await Promise.all([
    loadSeries(db, shiftDate(today, -11 * 366), [
      "TW_SIGNAL",
      "TW_LEADING",
      "TW_COINCIDENT",
      "US_CPI",
      "US_UNRATE",
      "FED_UPPER",
    ]),
    loadSeries(db, shiftDate(today, -5 * 366), ["UST2Y", "UST10Y"]),
    listMacroEvents(db, shiftDate(today, -120)),
  ]);
  const get = (list: LoadedSeries[], code: string) => list.find((s) => s.code === code)?.points ?? [];
  const tenYears = shiftDate(today, -10 * 366);
  const recent = (points: readonly SeriesPoint[]) => points.filter((p) => p.date >= tenYears);
  const signal = get(monthly, "TW_SIGNAL");
  const latest = signal.at(-1) as (SeriesPoint & { label: string | null }) | undefined;
  const ust2 = get(rates, "UST2Y");
  const ust10 = get(rates, "UST10Y");
  const upcoming = events.filter((e) => e.date >= today);
  const past = events.filter((e) => e.date < today).reverse();

  return (
    <div className="space-y-4">
      <InfoNote>
        景氣對策信號、領先與同時指標來自國發會（每月 27 日前後發布上個月，發布時會回溯修正歷史）；分數 9–16
        藍燈、17–22 黃藍燈、23–31 綠燈、32–37 黃紅燈、38–45 紅燈。美國利率、CPI、失業率來自 FRED。燈號變色或
        Fed 調整利率時會發出警示。行事曆的 Fed 2026 年會議日期取自聯準會網站，其他事件可在 /admin 新增。
      </InfoNote>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="景氣對策信號"
          description={
            latest ? `${latest.date.slice(0, 7)}：${latest.label ?? ""} ${latest.value} 分` : "尚無資料"
          }
        >
          <TimeChart
            label="景氣對策信號分數"
            format="price"
            period="month"
            series={[line("分數", recent(signal))]}
          />
          {signal.length ? (
            <Table className="mt-3">
              <TableHeader>
                <TableRow>
                  <TableHead>月份</TableHead>
                  <TableHead className="text-right">分數</TableHead>
                  <TableHead>燈號</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <ShowMoreRows
                  initial={3}
                  colSpan={3}
                  rows={signal
                    .slice(-12)
                    .reverse()
                    .map((p) => (
                      <TableRow key={p.date}>
                        <TableCell className="tabular-nums">{p.date.slice(0, 7)}</TableCell>
                        <TableCell className="text-right tabular-nums">{p.value}</TableCell>
                        <TableCell>{p.label}</TableCell>
                      </TableRow>
                    ))}
                />
              </TableBody>
            </Table>
          ) : null}
        </ChartCard>

        <ChartCard title="領先與同時指標" description="不含趨勢指數，近 10 年">
          <TimeChart
            label="景氣指標"
            format="price"
            period="month"
            series={[
              line("領先指標", recent(get(monthly, "TW_LEADING"))),
              line("同時指標", recent(get(monthly, "TW_COINCIDENT")), "--series-2"),
            ]}
          />
        </ChartCard>

        <ChartCard title="美國公債殖利率" description="2 年與 10 年期，近 5 年">
          <TimeChart
            label="美債殖利率"
            format="percent"
            series={[
              line("2 年", percentToFraction(ust2)),
              line("10 年", percentToFraction(ust10), "--series-2"),
            ]}
          />
        </ChartCard>

        <ChartCard title="10 年減 2 年利差" description="負值為殖利率曲線倒掛">
          <TimeChart
            label="利差"
            format="percent"
            series={[line("利差", percentToFraction(spread(ust10, ust2)))]}
          />
        </ChartCard>

        <ChartCard title="Fed 利率目標上限" description="近 10 年">
          <TimeChart
            label="Fed 利率"
            format="percent"
            series={[line("目標上限", percentToFraction(recent(get(monthly, "FED_UPPER"))))]}
          />
        </ChartCard>

        <ChartCard title="美國 CPI 年增率與失業率" description="近 10 年">
          <TimeChart
            label="美國通膨與就業"
            format="percent"
            period="month"
            series={[
              line("CPI 年增率", recent(yearOverYear(get(monthly, "US_CPI")))),
              line("失業率", percentToFraction(recent(get(monthly, "US_UNRATE"))), "--series-2"),
            ]}
          />
        </ChartCard>
      </div>

      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">事件行事曆</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <EventList title="即將到來" events={upcoming} empty="沒有排定的事件" />
          <EventList title="最近" events={past} empty="近 4 個月沒有事件" />
        </CardContent>
      </Card>
    </div>
  );
}

function EventList({
  title,
  events,
  empty,
}: {
  title: string;
  events: Awaited<ReturnType<typeof listMacroEvents>>;
  empty: string;
}) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">{title}</h3>
      {events.length ? (
        <ul className="divide-y text-sm">
          {events.slice(0, 8).map((e) => (
            <li key={e.id} className="flex items-baseline gap-2 py-1.5">
              <span className="w-20 shrink-0 text-muted-foreground tabular-nums">{e.date}</span>
              <Badge variant="secondary">{EVENT_KIND_LABEL[e.kind]}</Badge>
              <span>{e.title}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}
