import { ChevronRight } from "lucide-react";

/**
 * Rotates when its own `<details>` opens; a `group-open` variant would also follow an
 * open outer `<details>`. Put it directly in the `<summary>`.
 */
export const DISCLOSURE_CHEVRON =
  "size-4 shrink-0 text-muted-foreground transition-transform [details[open]>summary>&]:rotate-90";

/**
 * Native `<details>` with a chevron: works in server components, keeps the content in the
 * HTML (find-in-page still reaches it) and needs no client state.
 */
export function Disclosure({
  summary,
  meta,
  defaultOpen = false,
  className,
  children,
}: {
  summary: React.ReactNode;
  /** Right-aligned text in the summary row (counts, dates). */
  meta?: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <details open={defaultOpen} className={className}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className={DISCLOSURE_CHEVRON} aria-hidden />
        <span className="min-w-0 flex-1 font-medium">{summary}</span>
        {meta ? <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{meta}</span> : null}
      </summary>
      <div className="pt-3">{children}</div>
    </details>
  );
}

/** A collapsed 「說明」 line for long explanations that used to sit in card headers. */
export function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="inline-flex cursor-pointer list-none items-center gap-0.5 select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
        說明
        <ChevronRight className="size-3 transition-transform [details[open]>summary>&]:rotate-90" aria-hidden />
      </summary>
      <div className="mt-1 leading-relaxed">{children}</div>
    </details>
  );
}
