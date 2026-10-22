"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";

import { memoryEntry, remember, rememberedUrl, subscribe } from "@/lib/nav-memory";

/** `href` (a top-level page), or the URL that page was last left at (lib/nav-memory). */
export function useRememberedHref(href: string): string {
  return useSyncExternalStore(
    subscribe,
    () => rememberedUrl(href),
    // The server and the first client render use the plain URL (no hydration mismatch).
    () => href,
  );
}

/** A link to a top-level page that returns to its remembered tabs and options. */
export function RememberedLink({
  href,
  ...props
}: React.ComponentProps<typeof Link> & { href: string }) {
  return <Link href={useRememberedHref(href)} {...props} />;
}

/** Records the current URL of top-level pages. Rendered once, inside <Suspense>. */
export function NavMemoryRecorder() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  useEffect(() => {
    const entry = memoryEntry(pathname, search);
    if (entry) remember(...entry);
  }, [pathname, search]);
  return null;
}
