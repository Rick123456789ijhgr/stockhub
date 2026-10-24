"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Wraps a live number: when `value` changes (not on the first render) the wrapper washes
 * briefly in the direction color (`.flash-up` / `.flash-down` in globals.css; off under
 * prefers-reduced-motion). D-125.
 */
export function FlashValue({
  value,
  className,
  children,
}: {
  value: number | null;
  className?: string;
  children: React.ReactNode;
}) {
  const [previous, setPrevious] = useState(value);
  const [flash, setFlash] = useState<{ direction: "up" | "down" | null; count: number }>({
    direction: null,
    count: 0,
  });
  if (value !== previous) {
    // Adjusting state while rendering (React's "storing information from previous renders").
    setPrevious(value);
    if (previous !== null && value !== null) {
      setFlash({ direction: value > previous ? "up" : "down", count: flash.count + 1 });
    }
  }
  return (
    <span
      // A new key restarts the animation when the value changes again within it.
      key={flash.count}
      data-flash={flash.direction ?? undefined}
      className={cn("-mx-1 rounded-md px-1", flash.direction && `flash-${flash.direction}`, className)}
    >
      {children}
    </span>
  );
}
