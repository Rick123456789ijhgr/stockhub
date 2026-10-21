import type { Kysely } from "kysely";
import Link from "next/link";

import { InfoNote } from "@/components/disclosure";
import { PriceChange } from "@/components/price-change";
import { ShowMoreRows } from "@/components/show-more";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DB } from "@/lib/db";
import { HEATMAP_PERIODS, type HeatmapPeriod } from "@/lib/heatmap-data";
import { loadHeatmap } from "@/lib/heatmap";
import { cn } from "@/lib/utils";

import { Heatmap, HeatmapLegend } from "./heatmap";

export type HeatmapBy = "industry" | "theme";

const BY_LABEL: Record<HeatmapBy, string> = { industry: "產業", theme: "題材" };
const PERIOD_LABEL: Record<HeatmapPeriod, string> = {
  "1d": "1 日",
  "5d": "5 日",
  "20d": "20 日",
};

export function parseHeatmapParams(query: Record<string, string | string[] | undefined>) {
  const by: HeatmapBy = query.by === "theme" ? "theme" : "industry";
  const period: HeatmapPeriod =
    typeof query.period === "string" && query.period in HEATMAP_PERIODS
      ? (query.period as HeatmapPeriod)
      : "1d";
  return { by, period };
}

function Segmented<K extends string>({
  options,
  active,
  href,
  label,
}: {
  options: Record<K, string>;
  active: K;
  href: (key: K) => string;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border p-0.5 text-sm">
      {(Object.keys(options) as K[]).map((key) => (
        <Link
          key={key}
          href={href(key)}
          scroll={false}
          aria-current={key === active ? "true" : undefined}
          className={cn(
            "rounded-[5px] px-2.5 py-1",
            key === active
              ? "bg-muted font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {options[key]}
        </Link>
      ))}
    </div>
  );
}

/** 產業與題材熱力圖: market-cap treemap coloured by change, with a table of the groups. */
export async function HeatmapSection({
  db,
  by,
  period,
}: {
  db: Kysely<DB>;
  by: HeatmapBy;
  period: HeatmapPeriod;
}) {
  const data = await loadHeatmap(db, by, period);
  const href = (b: HeatmapBy, p: HeatmapPeriod) => `/market?tab=heatmap&by=${b}&period=${p}`;
  const days = HEATMAP_PERIODS[period];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented label="分組" options={BY_LABEL} active={by} href={(b) => href(b, period)} />
        <Segmented label="期間" options={PERIOD_LABEL} active={period} href={(p) => href(by, p)} />
        {data ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            {data.baseDate ? `${data.baseDate} → ` : ""}
            {data.date} 收盤
          </span>
        ) : null}
      </div>
      <InfoNote>
        方塊大小是市值（收盤價 ×
        發行股數），顏色是期間漲跌幅（還原權息後），紅漲綠跌依外觀設定。群組漲跌是成分股以期初市值加權的報酬。只含上市櫃普通股（不含
        ETF）；只用收盤資料，盤中不更新。題材在 /admin
        編輯，一檔股票可以屬於多個題材。點群組標題放大，點個股進個股頁。
      </InfoNote>
      {!data ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">還沒有日線資料。</CardContent>
        </Card>
      ) : !data.groups.length ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {by === "theme" ? (
              <>
                還沒有題材。到{" "}
                <Link href="/admin?tab=themes" className="underline">
                  /admin
                </Link>{" "}
                新增題材與成分股。
              </>
            ) : (
              "沒有可顯示的股票。"
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          <HeatmapLegend days={days} />
          <Heatmap key={`${by}-${period}`} groups={data.groups} days={days} />
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">
                {BY_LABEL[by]}漲跌（{PERIOD_LABEL[period]}）
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{BY_LABEL[by]}</TableHead>
                    <TableHead className="text-right">漲跌</TableHead>
                    <TableHead className="text-right">市值（億）</TableHead>
                    <TableHead className="text-right">檔數</TableHead>
                    <TableHead className="hidden sm:table-cell">最大成分股</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <ShowMoreRows
                    initial={10}
                    colSpan={5}
                    rows={[...data.groups]
                      .sort((a, b) => (b.change ?? -Infinity) - (a.change ?? -Infinity))
                      .map((g) => (
                        <TableRow key={g.key}>
                          <TableCell>{g.name}</TableCell>
                          <TableCell className="text-right">
                            {g.change === null ? "—" : <PriceChange value={g.change * 100} suffix="%" />}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {(g.marketCap / 1e8).toLocaleString("zh-TW", {
                              maximumFractionDigits: 0,
                            })}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{g.members.length}</TableCell>
                          <TableCell className="hidden sm:table-cell">
                            {g.members.slice(0, 3).map((m, i) => (
                              <span key={m.id}>
                                {i ? "、" : ""}
                                <Link href={`/stocks/${m.symbol}`} className="hover:underline">
                                  {m.name}
                                </Link>
                              </span>
                            ))}
                          </TableCell>
                        </TableRow>
                      ))}
                  />
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
