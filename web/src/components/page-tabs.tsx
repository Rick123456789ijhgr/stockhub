import Link from "next/link";

import { cn } from "@/lib/utils";

export type PageTab<K extends string> = { key: K; label: string; badge?: number };

/** The tab in `?tab=` if it is one of `tabs`, else the first. */
export function activeTab<K extends string>(tabs: readonly PageTab<K>[], value: unknown): K {
  const found = tabs.find((t) => t.key === value);
  return (found ?? tabs[0]!).key;
}

/**
 * Underlined tab bar driven by `?tab=`: the server renders only the active tab, so a tab's
 * queries run only when it is opened. Other query parameters are dropped on switch.
 */
export function PageTabs<K extends string>({
  tabs,
  active,
  basePath,
  className,
}: {
  tabs: readonly PageTab<K>[];
  active: K;
  basePath: string;
  className?: string;
}) {
  return (
    <nav
      aria-label="分頁"
      className={cn("-mx-4 overflow-x-auto border-b px-4 md:mx-0 md:px-0", className)}
    >
      <ul className="flex gap-4 text-sm whitespace-nowrap">
        {tabs.map((tab, i) => {
          const current = tab.key === active;
          return (
            <li key={tab.key}>
              <Link
                href={i === 0 ? basePath : `${basePath}?tab=${tab.key}`}
                scroll={false}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex items-center gap-1.5 border-b-2 py-2",
                  current
                    ? "border-foreground font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
                {tab.badge ? (
                  <span className="rounded-full bg-muted px-1.5 text-xs text-muted-foreground tabular-nums">
                    {tab.badge.toLocaleString("zh-TW")}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
