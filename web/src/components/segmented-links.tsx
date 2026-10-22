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
