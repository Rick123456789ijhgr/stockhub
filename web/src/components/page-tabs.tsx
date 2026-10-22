import Link from "next/link";

import { LinkPending } from "@/components/nav/nav-progress";
import { cn } from "@/lib/utils";

export type PageTab<K extends string> = { key: K; label: string; badge?: number };

/** The tab in `?tab=` if it is one of `tabs`, else the first. */
export function activeTab<K extends string>(tabs: readonly PageTab<K>[], value: unknown): K {
  const found = tabs.find((t) => t.key === value);
  return (found ?? tabs[0]!).key;
}

/** Link of a tab: the first tab is the bare path; `query` is kept on every tab. */
export function tabHref(
  basePath: string,
  key: string,
  first: boolean,
  query: Record<string, string> = {},
): string {
  const params = new URLSearchParams(query);
  if (!first) params.set("tab", key);
  const search = params.toString();
  return search ? `${basePath}?${search}` : basePath;
}

/**
 * Underlined tab bar driven by `?tab=`: the server renders only the active tab, so a tab's
 * queries run only when it is opened. Other query parameters are dropped on switch, except
 * those in `query`.
 */
export function PageTabs<K extends string>({
  tabs,
  active,
  basePath,
  query,
  className,
}: {
  tabs: readonly PageTab<K>[];
  active: K;
  basePath: string;
  query?: Record<string, string>;
  className?: string;
}) {
  return (
    <nav
      aria-label="分頁"
      className={cn(
        "-mx-4 overflow-x-auto overflow-y-hidden border-b px-4 [scrollbar-width:none] md:mx-0 md:px-0",
        className,
      )}
    >
      <ul className="flex gap-6 text-sm whitespace-nowrap">
        {tabs.map((tab, i) => {
          const current = tab.key === active;
          return (
            <li key={tab.key}>
              <Link
                href={tabHref(basePath, tab.key, i === 0, query)}
                scroll={false}
                aria-current={current ? "page" : undefined}
                className={cn(
                  // Inset underline: a negative margin would overflow the scroll box and
                  // show a vertical scrollbar.
                  "inline-flex items-center gap-1.5 py-2.5",
                  current
                    ? "font-medium text-foreground shadow-[inset_0_-2px_0_var(--foreground)]"
                    : // Clicked: underline at once while the tab loads (LinkPending).
                      "text-muted-foreground hover:text-foreground has-data-link-pending:text-foreground has-data-link-pending:shadow-[inset_0_-2px_0_var(--foreground)]",
                )}
              >
                {tab.label}
                {tab.badge ? (
                  <span className="rounded-full bg-muted px-1.5 text-xs text-muted-foreground tabular-nums">
                    {tab.badge.toLocaleString("zh-TW")}
                  </span>
                ) : null}
                <LinkPending />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
