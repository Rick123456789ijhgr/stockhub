"use client";

import { useLinkStatus } from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

/** A navigation that has not finished by then is given up on (it failed, or the click was
 * cancelled). */
const GIVE_UP_MS = 15_000;

/** The in-app URL a click on `event` will navigate to, or null when it will not. */
export function navigationTarget(event: MouseEvent, location: Location): string | null {
  if (event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const anchor = (event.target as Element | null)?.closest?.("a[href]");
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if (anchor.target && anchor.target !== "_self") return null;
  if (anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.href, location.href);
  if (url.origin !== location.origin) return null;
  const target = url.pathname + url.search;
  return target === location.pathname + location.search ? null : target;
}

/**
 * Thin bar at the top while a navigation is on its way (pages block until ready instead of
 * showing skeletons, docs/DECISIONS.md D-118). It watches clicks on any in-app link, so
 * links need no changes; the bar only fades in after a short delay (CSS), so the usual
 * 30–150 ms switch shows nothing. Rendered inside <Suspense> (useSearchParams).
 */
export function NavProgress() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const [pendingFor, setPendingFor] = useState<string | null>(null);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = navigationTarget(event, window.location);
      if (target) setPendingFor(target);
    };
    // Capture phase: <Link> calls preventDefault() to navigate on the client, so a bubble
    // listener could not tell its clicks from cancelled ones. A click that ends up not
    // navigating is cleared by the timeout below.
    document.addEventListener("click", onClick, { capture: true });
    return () => document.removeEventListener("click", onClick, { capture: true });
  }, []);

  // The URL changed: the navigation (or a back/forward) has landed. Adjusting state while
  // rendering is React's pattern for resetting on a prop change.
  const [landed, setLanded] = useState(`${pathname}?${search}`);
  if (landed !== `${pathname}?${search}`) {
    setLanded(`${pathname}?${search}`);
    setPendingFor(null);
  }

  useEffect(() => {
    if (pendingFor === null) return;
    const id = window.setTimeout(() => setPendingFor(null), GIVE_UP_MS);
    return () => window.clearTimeout(id);
  }, [pendingFor]);

  if (pendingFor === null) return null;
  return (
    <div
      role="progressbar"
      aria-label="載入中"
      className="nav-progress pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 origin-left bg-primary"
    />
  );
}

/**
 * Placed inside a nav or tab <Link>: while that link's navigation is pending it renders a
 * marker, so the link can take its active look at once (`has-data-link-pending:` variants).
 */
export function LinkPending() {
  const { pending } = useLinkStatus();
  return pending ? <span data-link-pending hidden /> : null;
}
