"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { isSessionOpen } from "@/lib/market-hours";

/**
 * Re-renders the page's server components every `seconds` while the Taipei session is
 * open, so pages built from quotes_latest follow the 30-second poll.
 */
export function SessionRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = window.setInterval(() => {
      if (isSessionOpen(new Date()) && document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => window.clearInterval(id);
  }, [router, seconds]);
  return null;
}
