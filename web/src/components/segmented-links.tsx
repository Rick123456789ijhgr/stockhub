import { Check } from "lucide-react";
import Link from "next/link";

import { LinkPending } from "@/components/nav/nav-progress";
import { cn } from "@/lib/utils";

/**
 * Look of every segmented control (links here, buttons in charts and forms): a muted track
 * with the chosen option raised as a small card (D-125).
 */
export const SEGMENTED_GROUP = "inline-flex rounded-lg bg-muted p-0.5";

export function segmentedOption(active: boolean): string {
  return cn(
    "rounded-md px-2.5 py-1 transition-[background-color,color,box-shadow] duration-150",
    active ? "bg-card font-medium text-foreground shadow-card" : "text-muted-foreground hover:text-foreground",
  );
}

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
    <div role="group" aria-label={label} className={cn(SEGMENTED_GROUP, "text-sm")}>
      {(Object.keys(options) as K[]).map((key) => (
        <Link
          key={key}
          href={href(key)}
          scroll={false}
          aria-current={key === active ? "true" : undefined}
          className={cn(
            segmentedOption(key === active),
            key !== active && "has-data-link-pending:bg-card has-data-link-pending:text-foreground",
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
          "inline-flex items-center gap-1 rounded-md border px-2 py-1 transition-colors duration-150",
          on
            ? "border-brand/35 bg-brand-soft font-medium text-brand"
            : "border-dashed text-muted-foreground hover:border-solid hover:text-foreground has-data-link-pending:text-foreground",
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
