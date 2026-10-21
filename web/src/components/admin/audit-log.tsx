import { ShowMoreList } from "@/components/show-more";
import { formatTaipeiDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/audit";

const ACTION_LABEL: Record<string, string> = {
  "price_gap.confirm": "確認價格跳空事件",
  "price_gap.dismiss": "價格跳空：不是事件",
  "watchlist.add": "加入自選",
  "watchlist.remove": "移除自選",
  "watchlist.note": "修改自選備註",
  "watchlist.reorder": "調整自選順序",
  "settings.fees": "修改手續費設定",
  "portfolio.create": "新增交易",
  "portfolio.update": "修改交易",
  "portfolio.delete": "刪除交易",
  "portfolio.receipt": "輸入股利實收",
  "portfolio.receipt_clear": "股利改回估算",
  "jobs.request": "排入資料任務",
  "financials.quarantine_accept": "採用隔離的財報",
  "financials.quarantine_reject": "捨棄隔離的財報",
  "chips.quarantine_accept": "採用隔離的籌碼資料",
  "chips.quarantine_reject": "捨棄隔離的籌碼資料",
  "markets.quarantine_accept": "採用隔離的市場資料",
  "markets.quarantine_reject": "捨棄隔離的市場資料",
  "theme.create": "新增題材",
  "theme.update": "修改題材",
  "theme.delete": "刪除題材",
  "theme.add_stock": "題材加入成分股",
  "theme.end_stock": "題材移出成分股",
  "theme.remove_stock": "刪除題材成分股紀錄",
  "macro_event.create": "新增總經事件",
  "macro_event.delete": "刪除總經事件",
};

const SHOWN = 20;

/** Newest-first audit entries, one line each; a row opens to its detail JSON. */
export function AuditLogList({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">還沒有任何手動操作紀錄。</p>;
  }
  return (
    <ShowMoreList
      className="divide-y text-sm"
      initial={SHOWN}
      step={SHOWN}
      items={entries.map((e) => (
        <li key={e.id} className="py-1.5">
          <details className="group/audit">
            <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-0.5 [&::-webkit-details-marker]:hidden">
              <span className="text-xs text-muted-foreground tabular-nums">
                {formatTaipeiDateTime(e.at)}
              </span>
              <span className="font-medium">{ACTION_LABEL[e.action] ?? e.action}</span>
              {e.target ? <span className="font-mono text-xs">{e.target}</span> : null}
              <span className="text-xs text-muted-foreground">{e.actor}</span>
              <span className="ml-auto text-xs text-muted-foreground group-open/audit:hidden">內容</span>
            </summary>
            <pre className="mt-1 overflow-x-auto rounded bg-muted/50 p-2 text-xs">
              {JSON.stringify(e.detail, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    />
  );
}
