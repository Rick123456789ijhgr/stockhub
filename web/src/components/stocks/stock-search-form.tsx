import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

/** Search by symbol or name; results open on /stocks?q=. */
export function StockSearchForm({
  defaultValue = "",
  compact = false,
  className,
}: {
  defaultValue?: string;
  /** The narrow column on a stock's page: icon button, shorter placeholder. */
  compact?: boolean;
  className?: string;
}) {
  return (
    <form action="/stocks" className={cn("flex gap-2", className)} role="search">
      <label className="relative min-w-0 flex-1">
        <span className="sr-only">代號或名稱</span>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          name="q"
          defaultValue={defaultValue}
          placeholder={compact ? "代號或名稱" : "例如 2330、台積電、0050"}
          inputMode="search"
          autoComplete="off"
          className="h-10 w-full rounded-md border bg-background pr-3 pl-9 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
        />
      </label>
      <button
        type="submit"
        className="h-10 shrink-0 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
      >
        搜尋
      </button>
    </form>
  );
}
