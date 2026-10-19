/**
 * Display preferences kept in the browser (localStorage): color theme and the price-color
 * convention. Applied to <html> as the `dark` class and `data-price-colors` before first
 * paint by APPEARANCE_SCRIPT, and live by applyAppearance().
 */

export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];
export const PRICE_COLORS = ["tw", "intl"] as const;
export type PriceColors = (typeof PRICE_COLORS)[number];

export const THEME_KEY = "stockhub:theme";
export const PRICE_COLORS_KEY = "stockhub:price-colors";
/** Fired on window after a preference changes, so every control re-reads it. */
export const APPEARANCE_EVENT = "stockhub:appearance";

export function parseTheme(value: string | null | undefined): Theme {
  return THEMES.includes(value as Theme) ? (value as Theme) : "system";
}

export function parsePriceColors(value: string | null | undefined): PriceColors {
  return PRICE_COLORS.includes(value as PriceColors) ? (value as PriceColors) : "tw";
}

/** Whether the page should be dark for a preference and the OS setting. */
export function isDark(theme: Theme, systemDark: boolean): boolean {
  return theme === "dark" || (theme === "system" && systemDark);
}

/** Next theme for the one-button toggle: system → light → dark → system. */
export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // storage blocked (private mode, policies): fall back to defaults
  }
}

export function readTheme(): Theme {
  return parseTheme(read(THEME_KEY));
}

export function readPriceColors(): PriceColors {
  return parsePriceColors(read(PRICE_COLORS_KEY));
}

/** Store (when given) and apply the preferences to <html>. */
export function applyAppearance(update: { theme?: Theme; priceColors?: PriceColors } = {}): void {
  try {
    if (update.theme) window.localStorage.setItem(THEME_KEY, update.theme);
    if (update.priceColors) window.localStorage.setItem(PRICE_COLORS_KEY, update.priceColors);
  } catch {
    // not persisted, still applied below for this page view
  }
  const theme = update.theme ?? readTheme();
  const priceColors = update.priceColors ?? readPriceColors();
  const root = document.documentElement;
  const dark = isDark(theme, window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  root.dataset.priceColors = priceColors;
  window.dispatchEvent(new Event(APPEARANCE_EVENT));
}

/**
 * Inline <head> script: same logic as applyAppearance (kept self-contained, it runs before
 * any bundle), plus following the OS setting while the theme is "system".
 */
export const APPEARANCE_SCRIPT = `(function(){
var d=document.documentElement,m=window.matchMedia("(prefers-color-scheme: dark)");
function g(k){try{return localStorage.getItem(k)}catch(e){return null}}
function a(){var t=g(${JSON.stringify(THEME_KEY)}),p=g(${JSON.stringify(PRICE_COLORS_KEY)});
var k=t==="dark"||(t!=="light"&&m.matches);
d.classList.toggle("dark",k);d.style.colorScheme=k?"dark":"light";
d.dataset.priceColors=p==="intl"?"intl":"tw";}
a();m.addEventListener("change",a);})();`;
