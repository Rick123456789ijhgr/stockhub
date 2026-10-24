import { ChartCandlestick } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { ThemeToggle } from "@/components/appearance-controls";
import {
  BottomNav,
  BottomNavList,
  SidebarNav,
  SidebarNavList,
} from "@/components/nav/nav-links";
import { NavProgress } from "@/components/nav/nav-progress";
import { SessionRail } from "@/components/nav/session-rail";
import { NavMemoryRecorder } from "@/components/nav/remembered-link";
import { Skeleton } from "@/components/ui/skeleton";
import { UserMenu } from "@/components/user-menu";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { getSessionStatus } from "@/lib/session-status";

/**
 * Navigations between pages block until the new page is ready (30–150 ms locally) instead
 * of showing skeletons: React keeps a revealed fallback up for at least ~300 ms, so a
 * skeleton made every switch slower than the data (docs/DECISIONS.md D-118). Pages render
 * their content without a page-level <Suspense>; nav links and tabs show the pending state.
 */
export const instant = false;

/**
 * Signed-in shell: sidebar on desktop, bottom bar on mobile. The shell is static; page
 * content renders behind AuthGate, which re-checks the session on the server for every
 * page (the proxy is only the first gate).
 */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14rem_1fr]">
      <Suspense fallback={null}>
        <NavProgress />
        <NavMemoryRecorder />
      </Suspense>
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-sidebar-border bg-sidebar px-3 py-5 md:flex">
        <Brand />
        <Suspense fallback={<SidebarNavList pathname="" />}>
          <SidebarNav />
        </Suspense>
        <div className="mt-auto space-y-2 border-t border-sidebar-border px-1 pt-3">
          <ThemeToggle />
          <Suspense fallback={<Skeleton className="h-8 w-full" />}>
            <UserMenu />
          </Suspense>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b bg-background/80 px-4 backdrop-blur-md md:hidden">
          <Brand />
          <ThemeToggle />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-5 pb-24 md:px-8 md:py-8">
          <Suspense fallback={<div className="mb-6 h-5 md:mb-8" />}>
            <Session />
          </Suspense>
          <Suspense fallback={<PageSkeleton />}>
            <AuthGate>{children}</AuthGate>
          </Suspense>
        </main>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t bg-background/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden">
        <Suspense fallback={<BottomNavList pathname="" />}>
          <BottomNav />
        </Suspense>
      </div>
    </div>
  );
}

async function AuthGate({ children }: { children: React.ReactNode }) {
  await requireUser();
  return children;
}

/** The session rail above every page (D-126); refreshed with router.refresh(). */
async function Session() {
  await requireUser();
  const status = await getSessionStatus(getDb(), taipeiToday());
  return <SessionRail status={status} serverNow={new Date().toISOString()} />;
}

function Brand() {
  return (
    <Link href="/" className="group flex items-center gap-2 px-2 text-base font-semibold tracking-tight">
      <span className="grid size-7 place-items-center rounded-lg bg-brand text-primary-foreground shadow-card transition-transform duration-200 ease-out-soft group-hover:-rotate-6">
        <ChartCandlestick className="size-4" aria-hidden />
      </span>
      StockHub
    </Link>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="載入中">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}
