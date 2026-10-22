"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { MacroEvent } from "@/lib/markets";
import { sendJson } from "@/lib/send-json";
import { EVENT_KINDS, type EventKind } from "@/lib/theme-input";

const KIND_LABEL: Record<EventKind, string> = {
  fomc: "Fed",
  cbc: "央行",
  ndc_signal: "景氣燈號",
  other: "其他",
};
const SOURCE_LABEL: Record<MacroEvent["source"], string> = { seed: "預設", manual: "手動", auto: "自動" };

const field = "h-8 rounded-md border bg-background px-2 text-sm text-foreground";

/** Add and delete events of the macro calendar on /market; audited. */
export function MacroEventEditor({ events, today }: { events: MacroEvent[]; today: string }) {
  const router = useRouter();
  const [date, setDate] = useState(today);
  const [kind, setKind] = useState<EventKind>("cbc");
  const [title, setTitle] = useState("");
  const action = useMutation({
    mutationFn: ({ method, url, body }: { method: string; url: string; body?: unknown }) =>
      sendJson(method, url, body),
    onSuccess: () => router.refresh(),
  });
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate(
            { method: "POST", url: "/api/admin/macro-events", body: { date, kind, title } },
            { onSuccess: () => setTitle("") },
          );
        }}
      >
        <input
          type="date"
          className={field}
          aria-label="日期"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <select
          className={field}
          aria-label="種類"
          value={kind}
          onChange={(e) => setKind(e.target.value as EventKind)}
        >
          {EVENT_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <input
          className={`${field} min-w-0 flex-1`}
          placeholder="例如：央行理監事會"
          aria-label="事件"
          maxLength={100}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Button type="submit" size="sm" disabled={!title.trim() || action.isPending}>
          新增事件
        </Button>
        {action.error ? <span className="text-xs text-destructive">{action.error.message}</span> : null}
      </form>
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">沒有事件。</p>
      ) : (
        <ul className="divide-y text-sm">
          {events.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
              <span className="w-24 text-muted-foreground tabular-nums">{e.date}</span>
              <Badge variant="secondary">{KIND_LABEL[e.kind]}</Badge>
              <span>{e.title}</span>
              <span className="text-xs text-muted-foreground">{SOURCE_LABEL[e.source]}</span>
              <Button
                className="ml-auto"
                size="sm"
                variant="ghost"
                disabled={action.isPending}
                onClick={() => {
                  if (window.confirm(`刪除「${e.date} ${e.title}」？`)) {
                    action.mutate({ method: "DELETE", url: `/api/admin/macro-events/${e.id}` });
                  }
                }}
              >
                刪除
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
