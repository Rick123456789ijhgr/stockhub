import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { Kysely } from "kysely";

import { type ChartSeries, TimeChart } from "@/components/charts/time-chart";
import { JobButton } from "@/components/jobs/job-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatValue, periodLabel, type ValueFormat } from "@/lib/chart-format";
import type { DB } from "@/lib/db";
import {
  FINANCIAL_INDUSTRIES,
  getMonthlyRevenue,
  getQuarters,
  getSignals,
  type QuarterRow,
  type RevenueRow,
  type SignalRow,
} from "@/lib/fundamentals";

type StockInfo = { id: number; symbol: string; type: string; industry: string | null };

const CHART_QUARTERS = 20;
const TABLE_QUARTERS = 8;

function line(
  name: string,
  color: ChartSeries["color"],
  rows: QuarterRow[],
  pick: (q: QuarterRow) => number | null,
  kind: ChartSeries["kind"] = "line",
): ChartSeries {
  return { name, color, kind, data: rows.map((q) => ({ time: q.periodEnd, value: pick(q) })) };
}

/** 基本面: monthly revenue, margins, EPS, cash flow, ROE/DuPont, signals, quarterly table. */
export async function FundamentalsSection({ db, stock }: { db: Kysely<DB>; stock: StockInfo }) {
  if (stock.type === "etf") return null;
  if (stock.industry && FINANCIAL_INDUSTRIES.has(stock.industry)) {
    return (
      <section aria-labelledby="fundamentals" className="mt-6">
        <h2 id="fundamentals" className="mb-2 text-base font-semibold">
          基本面
        </h2>
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            金融保險業的財報科目（利息收入、保費收入、資本適足率等）和一般產業不同，將在 M3b
            提供。下方估值仍以每股盈餘與淨值計算。
          </CardContent>
        </Card>
      </section>
    );
  }
  const [quarters, revenue, signals] = await Promise.all([
    getQuarters(db, stock.id),
    getMonthlyRevenue(db, stock.id),
    getSignals(db, stock.id),
  ]);
  const refetch = (
    <JobButton
      size="xs"
      variant="ghost"
      label="重新抓取財報"
      requests={[{ job: "refresh_stock_fundamentals", params: { symbol: stock.symbol } }]}
    />
  );
  const withIncome = quarters.filter((q) => q.revenue !== null || q.eps !== null);
  if (withIncome.length === 0 && revenue.length === 0) {
    return (
      <section aria-labelledby="fundamentals" className="mt-6">
        <h2 id="fundamentals" className="mb-2 text-base font-semibold">
          基本面
        </h2>
        <Card>
          <CardContent className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            還沒有這家公司的財報（歷史回填進行中，或資料源沒有這家公司）。
            {refetch}
          </CardContent>
        </Card>
      </section>
    );
  }
  const recent = withIncome.slice(-CHART_QUARTERS);
  const latest = withIncome.at(-1);

  return (
    <section aria-labelledby="fundamentals" className="mt-6 space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="fundamentals" className="text-base font-semibold">
          基本面
        </h2>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {latest ? <span>最新財報 {periodLabel(latest.periodEnd, "quarter")}</span> : null}
          {refetch}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {revenue.length > 0 ? <RevenueCard rows={revenue} /> : null}
        {recent.length > 0 ? (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">獲利率（單季）</CardTitle>
            </CardHeader>
            <CardContent>
              <TimeChart
                label="獲利率"
                format="percent"
                period="quarter"
                series={[
                  line("毛利率", "--series-1", recent, (q) => q.grossMargin),
                  line("營業利益率", "--series-2", recent, (q) => q.operatingMargin),
                  line("稅後淨利率", "--series-3", recent, (q) => q.netMargin),
                ]}
              />
            </CardContent>
          </Card>
        ) : null}
        {recent.length > 0 ? (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">每股盈餘（單季，元）</CardTitle>
              <CardDescription>
                近四季合計 {formatValue(latest?.epsTtm, "eps")} 元
                {latest?.epsYoy !== null && latest?.epsYoy !== undefined
                  ? `，單季年增 ${formatValue(latest.epsYoy, "percent")}`
                  : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <TimeChart
                label="每股盈餘"
                format="eps"
                period="quarter"
                series={[line("EPS", "--series-1", recent, (q) => q.eps, "histogram")]}
              />
            </CardContent>
          </Card>
        ) : null}
        {recent.some((q) => q.operatingCashFlow !== null) ? (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">現金流（單季）</CardTitle>
              <CardDescription>
                自由現金流 = 營業現金流 − 資本支出；近四季合計{" "}
                {formatValue(latest?.freeCashFlowTtm, "hundredMillion")}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <TimeChart
                label="現金流"
                format="hundredMillion"
                period="quarter"
                series={[
                  line("自由現金流", "--series-1", recent, (q) => q.freeCashFlow, "histogram"),
                  line("營業現金流", "--series-2", recent, (q) => q.operatingCashFlow),
                ]}
              />
            </CardContent>
          </Card>
        ) : null}
        {recent.some((q) => q.roeTtm !== null) ? <DupontCard rows={recent} /> : null}
        <SignalsCard rows={signals} />
      </div>

      {withIncome.length > 0 ? <QuarterTable rows={withIncome.slice(-TABLE_QUARTERS)} /> : null}
      <p className="text-xs text-muted-foreground">
        財報為合併報表；單季數字由累計數換算（Q4 = 全年 − 前三季）。資料來源：證交所／櫃買中心
        OpenAPI（最新一季）與 FinMind（歷史）。2013 年以前（舊會計準則）不收錄。
      </p>
    </section>
  );
}

function RevenueCard({ rows }: { rows: RevenueRow[] }) {
  const recent = rows.slice(-36);
  const latest = rows.at(-1);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">月營收</CardTitle>
        {latest ? (
          <CardDescription className="tabular-nums">
            {periodLabel(latest.month, "month")}：{formatValue(latest.revenue, "hundredMillion")}
            ，年增 {formatValue(latest.yoy, "percent")}，累計年增 {formatValue(latest.ytdYoy, "percent")}
          </CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        <TimeChart
          label="月營收"
          format="hundredMillion"
          period="month"
          series={[
            {
              name: "營收",
              kind: "histogram",
              color: "--series-1",
              data: recent.map((r) => ({ time: r.month, value: r.revenue })),
            },
          ]}
        />
        <TimeChart
          label="月營收年增率"
          format="percent"
          period="month"
          height={140}
          series={[
            {
              name: "年增率",
              kind: "line",
              color: "--series-1",
              data: recent.map((r) => ({ time: r.month, value: r.yoy })),
            },
          ]}
        />
        <div className="overflow-x-auto rounded-lg border">
          <Table className="min-w-[28rem] text-xs">
            <TableHeader>
              <TableRow>
                <TableHead>月份</TableHead>
                <TableHead className="text-right">營收</TableHead>
                <TableHead className="text-right">月增</TableHead>
                <TableHead className="text-right">年增</TableHead>
                <TableHead className="text-right">累計年增</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows
                .slice(-6)
                .reverse()
                .map((r) => (
                  <TableRow key={r.month}>
                    <TableCell className="tabular-nums">{periodLabel(r.month, "month")}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatValue(r.revenue, "hundredMillion")}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatValue(r.mom, "percent")}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatValue(r.yoy, "percent")}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatValue(r.ytdYoy, "percent")}
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

function DupontCard({ rows }: { rows: QuarterRow[] }) {
  const tail = rows.slice(-4).reverse();
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">ROE 與杜邦分析（近四季）</CardTitle>
        <CardDescription>ROE = 淨利率 × 資產週轉率 × 權益乘數（平均資產與權益）</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <TimeChart
          label="ROE／ROA"
          format="percent"
          period="quarter"
          series={[
            line("ROE", "--series-1", rows, (q) => q.roeTtm),
            line("ROA", "--series-2", rows, (q) => q.roaTtm),
          ]}
        />
        <div className="overflow-x-auto rounded-lg border">
          <Table className="min-w-[28rem] text-xs">
            <TableHeader>
              <TableRow>
                <TableHead>季別</TableHead>
                <TableHead className="text-right">ROE</TableHead>
                <TableHead className="text-right">淨利率</TableHead>
                <TableHead className="text-right">資產週轉率</TableHead>
                <TableHead className="text-right">權益乘數</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tail.map((q) => (
                <TableRow key={q.periodEnd}>
                  <TableCell className="tabular-nums">{periodLabel(q.periodEnd, "quarter")}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatValue(q.roeTtm, "percent")}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatValue(q.dupontNetMargin, "percent")}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {q.dupontAssetTurnover === null ? "—" : `${q.dupontAssetTurnover.toFixed(2)} 次`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {q.dupontEquityMultiplier === null ? "—" : `${q.dupontEquityMultiplier.toFixed(2)} 倍`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

const DIRECTION = {
  up: { icon: TrendingUp, label: "改善" },
  down: { icon: TrendingDown, label: "轉弱" },
  neutral: { icon: Minus, label: "提示" },
} as const;

function SignalsCard({ rows }: { rows: SignalRow[] }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">重大變化提示</CardTitle>
        <CardDescription>規則式判斷（毛利率年變動 ≥ 3 個百分點、營收年增減 ≥ 30%、轉盈轉虧等），僅供參考。</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">近期沒有觸發的規則。</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {rows.map((s) => {
              const { icon: Icon, label } = DIRECTION[s.direction];
              return (
                <li key={`${s.code}-${s.periodEnd}`} className="flex items-start gap-2">
                  <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span>
                    <span className="sr-only">{label}：</span>
                    {s.title}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const TABLE_ROWS: { label: string; pick: (q: QuarterRow) => number | null; format: ValueFormat }[] = [
  { label: "營業收入", pick: (q) => q.revenue, format: "hundredMillion" },
  { label: "營業毛利", pick: (q) => q.grossProfit, format: "hundredMillion" },
  { label: "營業利益", pick: (q) => q.operatingIncome, format: "hundredMillion" },
  { label: "歸屬母公司淨利", pick: (q) => q.netIncomeParent, format: "hundredMillion" },
  { label: "每股盈餘（元）", pick: (q) => q.eps, format: "eps" },
  { label: "毛利率", pick: (q) => q.grossMargin, format: "percent" },
  { label: "營業利益率", pick: (q) => q.operatingMargin, format: "percent" },
  { label: "營收年增率", pick: (q) => q.revenueYoy, format: "percent" },
  { label: "營業現金流", pick: (q) => q.operatingCashFlow, format: "hundredMillion" },
  { label: "資本支出", pick: (q) => q.capitalExpenditure, format: "hundredMillion" },
  { label: "自由現金流", pick: (q) => q.freeCashFlow, format: "hundredMillion" },
  { label: "負債比率", pick: (q) => q.debtRatio, format: "percent" },
  { label: "流動比率", pick: (q) => q.currentRatio, format: "percent" },
  { label: "每股淨值（元）", pick: (q) => q.bvps, format: "eps" },
];

function QuarterTable({ rows }: { rows: QuarterRow[] }) {
  const columns = [...rows].reverse();
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">單季財報（近 {columns.length} 季）</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Wide table scrolls inside its own box on phones. */}
        <div className="overflow-x-auto rounded-lg border">
          <Table className="min-w-[44rem] text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-background">項目</TableHead>
                {columns.map((q) => (
                  <TableHead key={q.periodEnd} className="text-right tabular-nums">
                    {periodLabel(q.periodEnd, "quarter")}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {TABLE_ROWS.map((row) => (
                <TableRow key={row.label}>
                  <TableCell className="sticky left-0 bg-background">{row.label}</TableCell>
                  {columns.map((q) => (
                    <TableCell key={q.periodEnd} className="text-right tabular-nums">
                      {formatValue(row.pick(q), row.format)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
