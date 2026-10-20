"use client";

import { useEffect, useState } from "react";

/** Resolve a CSS custom property (any color syntax, incl. oklch) to rgba() for the canvas. */
export function cssColor(element: HTMLElement, name: string, alpha = 1): string {
  const value = getComputedStyle(element).getPropertyValue(name).trim();
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx || !value) return "rgba(128,128,128,1)";
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgba(${r},${g},${b},${((a / 255) * alpha).toFixed(3)})`;
}

/** Bumps when the theme or the price-color convention changes, so the chart repaints. */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    const observer = new MutationObserver(bump);
    for (const el of [document.documentElement, document.body]) {
      observer.observe(el, {
        attributes: true,
        attributeFilter: ["class", "data-theme", "data-price-colors"],
      });
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", bump);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", bump);
    };
  }, []);
  return version;
}
