"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-renders the server components of the current page every `seconds`. */
export function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = window.setInterval(() => router.refresh(), seconds * 1000);
    return () => window.clearInterval(id);
  }, [router, seconds]);
  return null;
}
