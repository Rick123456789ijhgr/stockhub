import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { ShowMoreList } from "@/components/show-more";
import { Badge } from "@/components/ui/badge";
import type { NewsListItem, NewsStock } from "@/lib/news";
import {
  CHANNEL_LABEL,
  EVENT_LABEL,
  relativeTime,
  sentimentLabel,
  sentimentTone,
  TONE_CLASS,
} from "@/lib/news-format";
import { cn } from "@/lib/utils";

const RELATION_LABEL: Record<NewsStock["relation"], string> = {
  direct: "",
  industry: "同產業",
  theme: "同題材",
};

function Sentiment({ item }: { item: NewsListItem }) {
  const tone = sentimentTone(item.sentiment);
  if (tone === null) return null;
  const label =
    item.sentimentSource === "author"
      ? tone === "up"
        ? "作者看多"
        : tone === "down"
          ? "作者看空"
          : "作者中性"
      : sentimentLabel(item.sentiment);
  return <span className={cn("tabular-nums", TONE_CLASS[tone])}>{label}</span>;
}

function Stocks({ stocks, current }: { stocks: NewsStock[]; current?: string }) {
  const shown = stocks.filter((s) => s.symbol !== current).slice(0, 8);
  if (shown.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1.5">
      {shown.map((s) => (
        <Link
          key={s.symbol}
          href={`/stocks/${s.symbol}?tab=news`}
          className={cn(
            "rounded-md border px-1.5 py-0.5 text-xs hover:bg-muted",
            s.relation !== "direct" && "border-dashed text-muted-foreground",
          )}
          title={RELATION_LABEL[s.relation] || undefined}
        >
          <span className="font-semibold tabular-nums">{s.symbol}</span> {s.name}
          {s.relation !== "direct" ? (
            <span className="text-muted-foreground"> {RELATION_LABEL[s.relation]}</span>
          ) : null}
        </Link>
      ))}
    </span>
  );
}

function Engagement({ item }: { item: NewsListItem }) {
  const m = item.meta ?? {};
  const parts: string[] = [];
  if (typeof m.pushes === "number") parts.push(`推 ${m.pushes}`);
  if (typeof m.boos === "number") parts.push(`噓 ${m.boos}`);
  if (typeof m.likes === "number") parts.push(`讚 ${m.likes}`);
  if (typeof m.comments === "number") parts.push(`留言 ${m.comments}`);
  if (parts.length === 0) return null;
  return <span className="tabular-nums">{parts.join("，")}</span>;
}

function NewsRow({
  item,
  now,
  showChannel,
  current,
}: {
  item: NewsListItem;
  now: Date;
  showChannel: boolean;
  current?: string;
}) {
  const important = (item.importance ?? 0) >= 4;
  return (
    <li className="space-y-1.5 py-3">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {showChannel ? <Badge variant="outline">{CHANNEL_LABEL[item.channel]}</Badge> : null}
        <span>{item.source}</span>
        <time dateTime={item.publishedAt} className="tabular-nums">
          {relativeTime(item.publishedAt, now)}
        </time>
        {item.eventType && item.eventType !== "other" ? (
          <span>{EVENT_LABEL[item.eventType] ?? item.eventType}</span>
        ) : null}
        {item.importance !== null ? (
          <span className={cn("tabular-nums", important && "font-medium text-foreground")}>
            重要度 {item.importance}
          </span>
        ) : null}
        <Sentiment item={item} />
        <Engagement item={item} />
      </p>
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group inline-flex items-start gap-1 font-medium leading-snug hover:underline"
      >
        <span>{item.title}</span>
        <ExternalLink
          className="mt-0.5 size-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100"
          aria-hidden
        />
      </a>
      {item.summary ? (
        <p className="text-sm text-muted-foreground">
          <span
            className="mr-1.5 rounded bg-muted px-1 py-0.5 text-[0.6875rem] text-foreground"
            title={[item.llmProvider, item.llmModel].filter(Boolean).join("：")}
          >
            AI 摘要
          </span>
          {item.summary}
        </p>
      ) : item.snippet && item.channel !== "social" ? (
        <p className="line-clamp-2 text-sm text-muted-foreground">{item.snippet}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Stocks stocks={item.stocks} current={current} />
        {item.duplicates > 0 ? (
          <span className="text-xs text-muted-foreground">另有 {item.duplicates} 則相同報導</span>
        ) : null}
      </div>
    </li>
  );
}

/**
 * News, announcements and forum posts as a list: source and time, the AI summary (marked as
 * such, with the model on hover), sentiment, and links to the stocks concerned. Titles link
 * to the original; full texts are never stored (D-138).
 */
export function NewsList({
  items,
  now,
  showChannel = false,
  current,
  initial = 15,
  empty,
}: {
  items: NewsListItem[];
  now: Date;
  showChannel?: boolean;
  /** Symbol of the page the list is on: its own chip is left out. */
  current?: string;
  initial?: number;
  empty: string;
}) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ShowMoreList
      className="divide-y"
      initial={initial}
      step={20}
      items={items.map((item) => (
        <NewsRow
          key={item.id}
          item={item}
          now={now}
          showChannel={showChannel}
          current={current}
        />
      ))}
    />
  );
}
