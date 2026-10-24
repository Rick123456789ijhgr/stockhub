/**
 * The interface color the user picks in /admin (D-129). Only one hex value is stored; CSS
 * derives the light and dark --brand, --brand-soft and --ring from it with relative color
 * syntax and clamps the lightness so links and buttons stay readable on either theme.
 */

/** null = the built-in indigo (oklch(0.51 0.2 274)). */
export type BrandColor = string | null;

export const BRAND_PRESETS: { label: string; value: BrandColor; swatch: string }[] = [
  { label: "靛藍（預設）", value: null, swatch: "#4f46e5" },
  { label: "藍", value: "#2563eb", swatch: "#2563eb" },
  { label: "青", value: "#0891b2", swatch: "#0891b2" },
  { label: "紫", value: "#7c3aed", swatch: "#7c3aed" },
  { label: "洋紅", value: "#c026d3", swatch: "#c026d3" },
  { label: "石墨", value: "#475569", swatch: "#475569" },
];

/** A stored value if it is a #rrggbb color (lower-cased), else null (the default). */
export function parseBrandColor(value: string | null | undefined): BrandColor {
  return value && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
}

/** OKLCH of an sRGB hex color: lightness 0..1, chroma, hue in degrees (0 for greys). */
export function hexToOklch(hex: string): { l: number; c: number; h: number } {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = [channel(0), channel(1), channel(2)];
  const l1 = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m1 = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s1 = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l1 + 0.793617785 * m1 - 0.0040720468 * s1;
  const A = 1.9779984951 * l1 - 2.428592205 * m1 + 0.4505937099 * s1;
  const B = 0.0259040371 * l1 + 0.7827717662 * m1 - 0.808675766 * s1;
  const c = Math.hypot(A, B);
  const h = c < 1e-4 ? 0 : ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360;
  return { l: L, c, h };
}

/** Hues of --red and --green in globals.css: the price colors. */
const PRICE_HUES = { red: 25, green: 150 } as const;
const HUE_WINDOW = 25;
/** Below this chroma a color reads as grey, whatever its hue. */
const MIN_CHROMA = 0.06;

/**
 * Which price color a pick could be mistaken for, if any: the brand marks the interface
 * (selection, focus, buttons), so a red or green one would read as "up" or "down".
 */
export function priceColorClash(hex: string): "red" | "green" | null {
  const { c, h } = hexToOklch(hex);
  if (c < MIN_CHROMA) return null;
  for (const [name, hue] of Object.entries(PRICE_HUES) as ["red" | "green", number][]) {
    const distance = Math.abs(((h - hue + 540) % 360) - 180);
    if (distance <= HUE_WINDOW) return name;
  }
  return null;
}
