"use client";

import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { rememberedUrl } from "@/lib/nav-memory";
import { cn } from "@/lib/utils";

/**
 * Search by symbol or name; results open on /stocks?q=. The clear button empties the box,
 * and on the results page also goes back to the list that was open before the search
 * (searching nothing does the same).
 */
export function StockSearchForm({
  defaultValue = "",
  compact = false,
  className,
}: {
  /** The current search, when showing its results. */
  defaultValue?: string;
  /** The narrow column on a stock's page: shorter placeholder. */
  compact?: boolean;
  className?: string;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(defaultValue);
  // A new search (or going back to the list) resets the box to the URL's query.
  const [shown, setShown] = useState(defaultValue);
  if (shown !== defaultValue) {
    setShown(defaultValue);
    setValue(defaultValue);
  }

  function clear() {
    setValue("");
    input.current?.focus();
    if (defaultValue) router.push(rememberedUrl("/stocks"));
  }

  return (
    <form
      action="/stocks"
      className={cn("flex gap-2", className)}
      role="search"
      onSubmit={(e) => {
        // An empty search is the list itself, with the tab that was open.
        if (value.trim()) return;
        e.preventDefault();
        router.push(rememberedUrl("/stocks"));
      }}
    >
      <label className="relative min-w-0 flex-1">
        <span className="sr-only">代號或名稱</span>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          ref={input}
          name="q"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && value) {
              e.preventDefault();
              clear();
            }
          }}
          placeholder={compact ? "代號或名稱" : "例如 2330、台積電、0050"}
          inputMode="search"
          autoComplete="off"
          className="h-10 w-full rounded-md border bg-background pr-9 pl-9 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
        />
        {value ? (
          <button
            type="button"
            onClick={clear}
            aria-label="清除"
            className="absolute top-1/2 right-1.5 grid size-7 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" aria-hidden />
          </button>
        ) : null}
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
