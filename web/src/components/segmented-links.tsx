import { Check } from "lucide-react";
import Link from "next/link";

import { LinkPending } from "@/components/nav/nav-progress";
import { cn } from "@/lib/utils";

/** A row of mutually exclusive options that are links (state lives in the URL). */
export function SegmentedLinks<K extends string>({
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
              : "text-muted-foreground hover:text-foreground has-data-link-pending:bg-muted has-data-link-pending:text-foreground",
          )}
        >
          {options[key]}
          <LinkPending />
        </Link>
      ))}
    </div>
  );
}

/**
 * Options that can be on together, as links (state lives in the URL). `href(key)` is the
 * URL with that option flipped, or null when it cannot be (the last one left on).
 */
export function ToggleLinks<K extends string>({
  options,
  selected,
  href,
  label,
}: {
  options: Record<K, string>;
  selected: readonly K[];
  href: (key: K) => string | null;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-1.5 text-xs">
      {(Object.keys(options) as K[]).map((key) => {
        const on = selected.includes(key);
        const to = href(key);
        const className = cn(
          "inline-flex items-center gap-1 rounded-md border px-2 py-1",
          on
            ? "border-foreground/25 bg-muted font-medium text-foreground"
            : "border-dashed text-muted-foreground hover:text-foreground has-data-link-pending:text-foreground",
        );
        const content = (
          <>
            <Check className={cn("size-3", on ? "" : "opacity-0")} aria-hidden />
            {options[key]}
          </>
        );
        return to === null ? (
          <span key={key} aria-pressed={on} aria-disabled title="至少要選一項" className={className}>
            {content}
          </span>
        ) : (
          <Link key={key} href={to} scroll={false} aria-pressed={on} className={className}>
            {content}
            <LinkPending />
          </Link>
        );
      })}
    </div>
  );
}
