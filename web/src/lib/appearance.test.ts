import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  APPEARANCE_SCRIPT,
  applyAppearance,
  BRAND_KEY,
  isDark,
  NAV_KEY,
  nextTheme,
  parseNavMode,
  parsePriceColors,
  parseTheme,
  PRICE_COLORS_KEY,
  readTheme,
  THEME_KEY,
} from "./appearance";

function mockSystemDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: dark, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

describe("appearance preferences", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
    delete document.documentElement.dataset.priceColors;
    document.documentElement.style.removeProperty("--brand-base");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("parses stored values with safe defaults", () => {
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme("blue")).toBe("system");
    expect(parseTheme(null)).toBe("system");
    expect(parsePriceColors("intl")).toBe("intl");
    expect(parsePriceColors("x")).toBe("tw");
    expect(parseNavMode("collapsed")).toBe("collapsed");
    expect(parseNavMode(null)).toBe("pinned");
  });

  it("resolves dark mode from the preference and the OS", () => {
    expect(isDark("dark", false)).toBe(true);
    expect(isDark("light", true)).toBe(false);
    expect(isDark("system", true)).toBe(true);
    expect(isDark("system", false)).toBe(false);
  });

  it("cycles the toggle through all themes", () => {
    expect([nextTheme("system"), nextTheme("light"), nextTheme("dark")]).toEqual([
      "light",
      "dark",
      "system",
    ]);
  });

  it("stores and applies preferences to <html>", () => {
    mockSystemDark(false);
    applyAppearance({ theme: "dark", priceColors: "intl" });
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(readTheme()).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.dataset.priceColors).toBe("intl");
    applyAppearance({ theme: "system" });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.dataset.nav).toBe("pinned");
    applyAppearance({ nav: "collapsed" });
    expect(localStorage.getItem(NAV_KEY)).toBe("collapsed");
    expect(document.documentElement.dataset.nav).toBe("collapsed");
  });

  it("sets and resets the interface color", () => {
    mockSystemDark(false);
    const base = () => document.documentElement.style.getPropertyValue("--brand-base");
    applyAppearance({ brand: "#2563EB" });
    expect(localStorage.getItem(BRAND_KEY)).toBe("#2563EB");
    expect(base()).toBe("#2563eb");
    applyAppearance({ theme: "dark" }); // other changes keep it
    expect(base()).toBe("#2563eb");
    applyAppearance({ brand: null });
    expect(localStorage.getItem(BRAND_KEY)).toBeNull();
    expect(base()).toBe("");
  });

  it("the inline head script applies the same preferences", () => {
    mockSystemDark(true);
    localStorage.setItem(PRICE_COLORS_KEY, "intl");
    localStorage.setItem(NAV_KEY, "collapsed");
    localStorage.setItem(BRAND_KEY, "#0891b2");
    new Function(APPEARANCE_SCRIPT)();
    expect(document.documentElement.style.getPropertyValue("--brand-base")).toBe("#0891b2");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.dataset.priceColors).toBe("intl");
    expect(document.documentElement.dataset.nav).toBe("collapsed");
    localStorage.setItem(THEME_KEY, "light");
    new Function(APPEARANCE_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
