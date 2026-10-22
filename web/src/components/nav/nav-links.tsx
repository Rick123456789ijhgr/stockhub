"use client";

import { usePathname } from "next/navigation";

import { LinkPending } from "@/components/nav/nav-progress";
import { RememberedLink } from "@/components/nav/remembered-link";
import { cn } from "@/lib/utils";

import { isActive, isMoreActive, MORE_ITEM, NAV_ITEMS, type NavItem } from "./nav-items";

/**
 * usePathname() is request data on dynamic routes (e.g. /stocks/[symbol]), so the layout
 * renders these inside <Suspense>; the `pathname=""` variants are the static fallbacks.
 */
export function SidebarNav() {
  return <SidebarNavList pathname={usePathname()} />;
}

export function SidebarNavList({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="主選單" className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => (
        <SidebarLink key={item.href} item={item} active={isActive(pathname, item.href)} />
      ))}
    </nav>
  );
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <RememberedLink
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : // Clicked: look active at once while the page loads (LinkPending).
            "has-data-link-pending:bg-sidebar-accent has-data-link-pending:text-sidebar-accent-foreground",
      )}
    >
      <Icon className="size-4" aria-hidden />
      {item.label}
      <LinkPending />
    </RememberedLink>
  );
}

export function BottomNav() {
  return <BottomNavList pathname={usePathname()} />;
}

export function BottomNavList({ pathname }: { pathname: string }) {
  const items = [...NAV_ITEMS.filter((item) => item.primary), MORE_ITEM];
  return (
    <nav aria-label="主選單" className="grid grid-cols-5">
      {items.map((item) => {
        const active =
          item.href === MORE_ITEM.href ? isMoreActive(pathname) : isActive(pathname, item.href);
        const Icon = item.icon;
        return (
          <RememberedLink
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground",
              active ? "font-medium text-foreground" : "has-data-link-pending:text-foreground",
            )}
          >
            <Icon className="size-5" aria-hidden />
            {item.label}
            <LinkPending />
          </RememberedLink>
        );
      })}
    </nav>
  );
}
