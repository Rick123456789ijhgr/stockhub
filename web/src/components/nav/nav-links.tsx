"use client";

import { Pin } from "lucide-react";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { LinkPending } from "@/components/nav/nav-progress";
import { RememberedLink } from "@/components/nav/remembered-link";
import { applyAppearance, type NavMode, readNavMode, subscribeAppearance } from "@/lib/appearance";
import { cn } from "@/lib/utils";

import { isActive, isMoreActive, MORE_ITEM, NAV_GROUPS, NAV_ITEMS, type NavItem } from "./nav-items";

/** A non-link row in the sidebar (pin, theme): same box as a nav item. */
export const SIDEBAR_ROW =
  "flex h-9 w-full items-center gap-3 rounded-lg px-3 text-sm whitespace-nowrap text-sidebar-foreground/75 transition-colors duration-150 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground";

/**
 * usePathname() is request data on dynamic routes (e.g. /stocks/[symbol]), so the layout
 * renders these inside <Suspense>; the `pathname=""` variants are the static fallbacks.
 */
export function SidebarNav() {
  return <SidebarNavList pathname={usePathname()} />;
}

/**
 * Grouped links with one highlight that slides to the clicked item (D-128). The highlight
 * is measured from the DOM after hydration; until then the current item paints its own
 * background, so the first paint already shows where you are.
 */
export function SidebarNavList({ pathname }: { pathname: string }) {
  const navRef = useRef<HTMLElement>(null);
  const [clicked, setClicked] = useState<{ href: string; from: string } | null>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);
  // A click only counts until the next page loads. Kept past that, an old click made from
  // this same path would pull the highlight back to it on a later visit (e.g. 個股 → 首頁
  // → a stock → back to 個股 left 首頁 highlighted).
  const [seenPath, setSeenPath] = useState(pathname);
  if (seenPath !== pathname) {
    setSeenPath(pathname);
    setClicked(null);
  }
  const current = NAV_ITEMS.find((item) => isActive(pathname, item.href))?.href ?? null;
  // A click moves the highlight at once; it settles on the page that actually loads.
  const target = clicked && clicked.from === pathname ? clicked.href : current;

  useLayoutEffect(() => {
    const el = target
      ? navRef.current?.querySelector<HTMLElement>(`[data-nav-href="${CSS.escape(target)}"]`)
      : null;
    setBox(el ? { top: el.offsetTop, height: el.offsetHeight } : null);
  }, [target]);

  return (
    <nav
      ref={navRef}
      aria-label="主選單"
      data-ready={box ? "" : undefined}
      data-highlight={target ?? undefined}
      className="group/nav relative flex flex-col"
    >
      {box ? (
        <span
          aria-hidden
          className="nav-highlight absolute inset-x-0 rounded-lg bg-brand-soft"
          style={{ transform: `translateY(${box.top}px)`, height: box.height }}
        />
      ) : null}
      {NAV_GROUPS.map((group) => (
        <div key={group.key} className="flex flex-col gap-0.5">
          {group.label ? (
            <div className="relative mt-3 mb-1 h-4 px-3 text-[11px] text-muted-foreground" aria-hidden>
              <span className="nav-conceal absolute top-1/2 left-3 h-px w-4 bg-sidebar-border" />
              <span className="nav-reveal absolute inset-0 px-3">{group.label}</span>
            </div>
          ) : null}
          {NAV_ITEMS.filter((item) => item.group === group.key).map((item) => (
            <SidebarLink
              key={item.href}
              item={item}
              active={item.href === current}
              onNavigate={() => setClicked({ href: item.href, from: pathname })}
            />
          ))}
        </div>
      ))}
    </nav>
  );
}

function SidebarLink({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;
  return (
    <RememberedLink
      href={item.href}
      data-nav-href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => {
        if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
          onNavigate();
        }
      }}
      className={cn(
        "relative flex h-9 items-center gap-3 rounded-lg px-3 text-sm whitespace-nowrap text-sidebar-foreground/75 transition-colors duration-150 hover:text-sidebar-accent-foreground",
        "before:absolute before:inset-0 before:-z-0 before:rounded-lg before:bg-sidebar-accent before:opacity-0 before:transition-opacity before:duration-150 hover:before:opacity-100",
        active
          ? "font-medium text-brand hover:text-brand hover:before:opacity-0 bg-brand-soft group-data-ready/nav:bg-transparent"
          : "has-data-link-pending:text-sidebar-accent-foreground",
      )}
    >
      <Icon className="relative size-4 shrink-0" aria-hidden />
      <span className="nav-reveal relative">{item.label}</span>
      <LinkPending />
    </RememberedLink>
  );
}

/** Pin the sidebar open or let it fold into the icon rail; the `[` key does the same. */
export function NavPinToggle() {
  const mode = useSyncExternalStore(subscribeAppearance, readNavMode, () => "pinned" as NavMode);
  const pinned = mode === "pinned";
  const toggle = useCallback(
    () => applyAppearance({ nav: readNavMode() === "pinned" ? "collapsed" : "pinned" }),
    [],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "[" || event.metaKey || event.ctrlKey || event.altKey) return;
      const el = event.target as HTMLElement | null;
      if (el?.closest("input, textarea, select, [contenteditable='true']")) return;
      event.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  const label = pinned ? "收起側邊欄" : "鎖定側邊欄";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={pinned}
      aria-label={label}
      title={`${label}（[）`}
      className={SIDEBAR_ROW}
    >
      <Pin
        className={cn(
          "size-4 shrink-0 transition-transform duration-200 ease-out-soft",
          pinned ? "rotate-0 text-brand" : "rotate-45",
        )}
        aria-hidden
      />
      <span className="nav-reveal">{label}</span>
    </button>
  );
}

export function BottomNav() {
  return <BottomNavList pathname={usePathname()} />;
}

export function BottomNavList({ pathname }: { pathname: string }) {
  const items = [...NAV_ITEMS.filter((item) => item.primary), MORE_ITEM];
  const activeIndex = items.findIndex((item) =>
    item.href === MORE_ITEM.href ? isMoreActive(pathname) : isActive(pathname, item.href),
  );
  return (
    <nav aria-label="主選單" className="relative grid grid-cols-5">
      {/* One pill behind the current icon; it slides across when the page changes (D-128). */}
      {activeIndex >= 0 ? (
        <span
          aria-hidden
          className="nav-highlight absolute top-1.5 h-7 w-12 rounded-full bg-brand-soft"
          style={{ left: `calc(${(activeIndex + 0.5) * 20}% - 1.5rem)` }}
        />
      ) : null}
      {items.map((item, i) => {
        const active = i === activeIndex;
        const Icon = item.icon;
        return (
          <RememberedLink
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground transition-colors",
              active ? "font-medium text-brand" : "has-data-link-pending:text-foreground",
            )}
          >
            <span className="grid h-7 w-12 place-items-center">
              <Icon className="size-5" aria-hidden />
            </span>
            {item.label}
            <LinkPending />
          </RememberedLink>
        );
      })}
    </nav>
  );
}
