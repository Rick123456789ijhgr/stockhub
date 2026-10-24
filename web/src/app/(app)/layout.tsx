import { ChartCandlestick } from "lucide-react";
import Link from "next/link";
import { cache, Suspense } from "react";

import { ThemeNavButton, ThemeToggle } from "@/components/appearance-controls";
import {
  BottomNav,
  BottomNavList,
  NavPinToggle,
  SIDEBAR_ROW,
  SidebarNav,
  SidebarNavList,
} from "@/components/nav/nav-links";
import { NavProgress } from "@/components/nav/nav-progress";
import {
  SessionClock,
  SessionPill,
  type SessionProps,
  SessionRing,
} from "@/components/nav/session-rail";
import { NavMemoryRecorder } from "@/components/nav/remembered-link";
import { StockHoverPreview } from "@/components/stocks/stock-hover-preview";
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
 * Signed-in shell: a sidebar on desktop that is pinned open or folds into an icon rail
 * (D-128), a top bar and bottom bar on mobile. The session clock lives in the sidebar
 * header (the top bar on phones) instead of above every page. Page content renders behind
 * AuthGate, which re-checks the session on the server for every page (the proxy is only
 * the first gate).
 */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="app-shell min-h-dvh">
      <Suspense fallback={null}>
        <NavProgress />
        <NavMemoryRecorder />
        <StockHoverPreview />
      </Suspense>
      <aside className="sticky top-0 z-30 hidden h-dvh md:block">
        <div className="nav-panel absolute inset-y-0 left-0 flex flex-col gap-4 overflow-x-hidden overflow-y-auto border-r border-sidebar-border bg-sidebar px-2 py-4">
          <div className="space-y-3">
            <Suspense fallback={<Brand ring={null} />}>
              <SessionBrand />
            </Suspense>
            <Suspense fallback={<div className="h-[3.25rem]" />}>
              <SidebarSession />
            </Suspense>
          </div>
          <Suspense fallback={<SidebarNavList pathname="" />}>
            <SidebarNav />
          </Suspense>
          <div className="mt-auto flex flex-col gap-0.5 border-t border-sidebar-border pt-3">
            <ThemeNavButton className={SIDEBAR_ROW} />
            <NavPinToggle />
            <div className="nav-reveal mt-1 h-8 px-1">
              <Suspense fallback={null}>
                <UserMenu />
              </Suspense>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between gap-3 border-b bg-background/80 px-4 backdrop-blur-md md:hidden">
          <Suspense fallback={<Brand ring={null} />}>
            <SessionBrand withPill />
          </Suspense>
          <ThemeToggle />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-5 pb-24 md:px-8 md:py-8">
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

/** One calendar and freshness lookup per request, shared by the brand ring and the clock. */
const loadSession = cache(async () => {
  await requireUser();
  const status = await getSessionStatus(getDb(), taipeiToday());
  return { status, serverNow: new Date().toISOString() };
});

async function SessionBrand({ withPill = false }: { withPill?: boolean }) {
  const session = await loadSession();
  return (
    <div className="flex items-center gap-3">
      <Brand ring={session} />
      {withPill ? <SessionPill {...session} /> : null}
    </div>
  );
}

async function SidebarSession() {
  return <SessionClock {...await loadSession()} />;
}

function Brand({ ring }: { ring: SessionProps | null }) {
  const mark = (
    <span className="grid size-7 place-items-center rounded-full bg-brand text-primary-foreground transition-transform duration-200 ease-out-soft group-hover:-rotate-6">
      <ChartCandlestick className="size-4" aria-hidden />
    </span>
  );
  return (
    <Link
      href="/"
      className="group flex items-center gap-2.5 rounded-lg pl-0.5 text-base font-semibold tracking-tight whitespace-nowrap"
    >
      {ring ? <SessionRing {...ring}>{mark}</SessionRing> : <span className="grid size-9 shrink-0 place-items-center">{mark}</span>}
      <span className="nav-reveal">StockHub</span>
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
