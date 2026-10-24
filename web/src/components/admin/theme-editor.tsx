"use client";

import { useMutation } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DISCLOSURE_CHEVRON } from "@/components/disclosure";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { sendJson } from "@/lib/send-json";
import type { Theme, ThemeMember } from "@/lib/themes";

const field =
  "h-8 rounded-md border bg-background px-2 text-sm text-foreground aria-invalid:border-destructive";

function useSend() {
  const router = useRouter();
  return useMutation({
    mutationFn: ({ method, url, body }: { method: string; url: string; body?: unknown }) =>
      sendJson(method, url, body),
    onSuccess: () => router.refresh(),
  });
}

function ErrorText({ error }: { error: Error | null }) {
  return error ? <span className="text-xs text-destructive">{error.message}</span> : null;
}

/** Create, rename and delete themes and edit their members over time; every change is audited. */
export function ThemeEditor({ themes, today }: { themes: Theme[]; today: string }) {
  const create = useSend();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { method: "POST", url: "/api/admin/themes", body: { name, description } },
            {
              onSuccess: () => {
                setName("");
                setDescription("");
              },
            },
          );
        }}
      >
        <input
          className={`${field} w-40`}
          placeholder="題材名稱"
          aria-label="題材名稱"
          maxLength={40}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className={`${field} min-w-0 flex-1`}
          placeholder="說明（選填）"
          aria-label="說明"
          maxLength={500}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Button type="submit" size="sm" disabled={!name.trim() || create.isPending}>
          新增題材
        </Button>
        <ErrorText error={create.error} />
      </form>
      {themes.length === 0 ? (
        <p className="text-sm text-muted-foreground">還沒有題材。</p>
      ) : (
        <ul className="divide-y">
          {themes.map((t) => (
            <ThemeItem key={t.id} theme={t} today={today} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ThemeItem({ theme, today }: { theme: Theme; today: string }) {
  const action = useSend();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(theme.name);
  const [description, setDescription] = useState(theme.description ?? "");
  const [symbol, setSymbol] = useState("");
  const [validFrom, setValidFrom] = useState(today);
  const current = theme.members.filter((m) => m.validTo === null || m.validTo >= today);
  const ended = theme.members.filter((m) => m.validTo !== null && m.validTo < today);
  const base = `/api/admin/themes/${theme.id}`;
  return (
    <li className="py-1.5 text-sm">
      <details>
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
          <ChevronRight className={DISCLOSURE_CHEVRON} aria-hidden />
          <span className="font-medium">{theme.name}</span>
          <span className="text-xs text-muted-foreground">{current.length} 檔</span>
          {theme.description ? (
            <span className="truncate text-xs text-muted-foreground">{theme.description}</span>
          ) : null}
        </summary>
        <div className="space-y-3 pt-2 pl-7">
          {editing ? (
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                action.mutate(
                  { method: "PATCH", url: base, body: { name, description } },
                  { onSuccess: () => setEditing(false) },
                );
              }}
            >
              <input
                className={`${field} w-40`}
                aria-label="題材名稱"
                maxLength={40}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <input
                className={`${field} min-w-0 flex-1`}
                aria-label="說明"
                maxLength={500}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <Button type="submit" size="sm" disabled={!name.trim() || action.isPending}>
                儲存
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                取消
              </Button>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                改名或說明
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={action.isPending}
                onClick={() => {
                  if (
                    window.confirm(`刪除題材「${theme.name}」與它的 ${theme.members.length} 筆成分股紀錄？`)
                  ) {
                    action.mutate({ method: "DELETE", url: base });
                  }
                }}
              >
                刪除題材
              </Button>
            </div>
          )}

          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              action.mutate(
                { method: "POST", url: `${base}/members`, body: { symbol, validFrom } },
                { onSuccess: () => setSymbol("") },
              );
            }}
          >
            <input
              className={`${field} w-24 tabular-nums uppercase`}
              placeholder="代號"
              aria-label="股票代號"
              maxLength={6}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            />
            <label className="flex items-center gap-1 text-xs text-muted-foreground">
              起始日
              <input
                type="date"
                className={field}
                value={validFrom}
                max={today}
                onChange={(e) => setValidFrom(e.target.value)}
              />
            </label>
            <Button type="submit" size="sm" disabled={!symbol.trim() || action.isPending}>
              加入
            </Button>
            <ErrorText error={action.error} />
          </form>

          {current.length ? (
            <ul className="divide-y">
              {current.map((m) => (
                <MemberRow key={`${m.stockId}-${m.validFrom}`} member={m} base={base} today={today} />
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">還沒有成分股。</p>
          )}
          {ended.length ? (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">已移出的成分股（{ended.length}）</summary>
              <ul className="divide-y">
                {ended.map((m) => (
                  <MemberRow key={`${m.stockId}-${m.validFrom}`} member={m} base={base} today={today} />
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </details>
    </li>
  );
}

function MemberRow({ member, base, today }: { member: ThemeMember; base: string; today: string }) {
  const action = useSend();
  const key = { stockId: member.stockId, validFrom: member.validFrom };
  const open = member.validTo === null;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1">
      <Link href={`/stocks/${member.symbol}`} className="hover:underline">
        <span className="font-semibold tabular-nums">{member.symbol}</span> {member.name}
      </Link>
      <span className="text-xs text-muted-foreground tabular-nums">
        {member.validFrom} ～ {member.validTo ?? "至今"}
      </span>
      {member.note ? <Badge variant="outline">{member.note}</Badge> : null}
      <div className="ml-auto flex items-center gap-1.5">
        <ErrorText error={action.error} />
        {open ? (
          <Button
            size="sm"
            variant="outline"
            disabled={action.isPending || member.validFrom > today}
            title="保留歷史：記錄今天是最後一天"
            onClick={() =>
              action.mutate({ method: "PATCH", url: `${base}/members`, body: { ...key, validTo: today } })
            }
          >
            移出
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          disabled={action.isPending}
          title="整筆刪除（加錯時用；回測會看不到這段期間）"
          onClick={() => {
            if (window.confirm(`刪除 ${member.symbol} 這段成分股紀錄？`)) {
              action.mutate({ method: "DELETE", url: `${base}/members`, body: key });
            }
          }}
        >
          刪除
        </Button>
      </div>
    </li>
  );
}
