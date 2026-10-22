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
import { NavMemoryRecorder } from "@/components/nav/remembered-link";
import { Skeleton } from "@/components/ui/skeleton";
import { UserMenu } from "@/components/user-menu";
import { requireUser } from "@/lib/auth/session";

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
    <div className="min-h-dvh md:grid md:grid-cols-[13rem_1fr]">
      <Suspense fallback={null}>
        <NavProgress />
        <NavMemoryRecorder />
      </Suspense>
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r bg-sidebar px-3 py-5 md:flex">
        <Brand />
        <Suspense fallback={<SidebarNavList pathname="" />}>
          <SidebarNav />
        </Suspense>
        <div className="mt-auto space-y-2 px-1">
          <ThemeToggle />
          <Suspense fallback={<Skeleton className="h-8 w-full" />}>
            <UserMenu />
          </Suspense>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b bg-background/95 px-4 backdrop-blur md:hidden">
          <Brand />
          <ThemeToggle />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-4 pb-24 md:px-8 md:py-6">
          <Suspense fallback={<PageSkeleton />}>
            <AuthGate>{children}</AuthGate>
          </Suspense>
        </main>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
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

function Brand() {
  return (
    <Link href="/" className="px-2 text-base font-semibold tracking-tight">
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
