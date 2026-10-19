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
};

/** Newest-first audit entries; the detail JSON is collapsed per row. */
export function AuditLogList({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">還沒有任何手動操作紀錄。</p>;
  }
  return (
    <ul className="divide-y text-sm">
      {entries.map((e) => (
        <li key={e.id} className="py-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <span className="text-xs text-muted-foreground tabular-nums">
              {formatTaipeiDateTime(e.at)}
            </span>
            <span className="font-medium">{ACTION_LABEL[e.action] ?? e.action}</span>
            {e.target ? <span className="font-mono text-xs">{e.target}</span> : null}
            <span className="text-xs text-muted-foreground">{e.actor}</span>
          </div>
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-muted-foreground">內容</summary>
            <pre className="mt-1 overflow-x-auto rounded bg-muted/50 p-2 text-xs">
              {JSON.stringify(e.detail, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    </ul>
  );
}
