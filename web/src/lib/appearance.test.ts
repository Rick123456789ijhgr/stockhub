import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  APPEARANCE_SCRIPT,
  applyAppearance,
  isDark,
  nextTheme,
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
  });
  afterEach(() => vi.unstubAllGlobals());

  it("parses stored values with safe defaults", () => {
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme("blue")).toBe("system");
    expect(parseTheme(null)).toBe("system");
    expect(parsePriceColors("intl")).toBe("intl");
    expect(parsePriceColors("x")).toBe("tw");
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
  });

  it("the inline head script applies the same preferences", () => {
    mockSystemDark(true);
    localStorage.setItem(PRICE_COLORS_KEY, "intl");
    new Function(APPEARANCE_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.dataset.priceColors).toBe("intl");
    localStorage.setItem(THEME_KEY, "light");
    new Function(APPEARANCE_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
