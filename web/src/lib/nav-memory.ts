/**
 * The last URL (with its tabs and options) seen on each top-level page, kept in the
 * browser (localStorage), so going back to a section from the menu or a back link returns
 * to where it was left: /stocks?tab=volume&type=all instead of /stocks
 * (docs/DECISIONS.md D-122). A per-viewer convenience only: when storage is unavailable the
 * links fall back to the bare page.
 */

const KEY = "stockhub.nav-memory";
const EVENT = "stockhub:nav-memory";

type Memory = Record<string, string>;

/** Pages whose state is remembered: the top-level pages (exact path, not sub-pages). */
export const REMEMBERED_PAGES = [
  "/portfolio",
  "/stocks",
  "/watchlist",
  "/news",
  "/market",
  "/screener",
  "/backtest",
  "/status",
  "/admin",
] as const;

/**
 * The URL to remember for `pathname` + `search`, under which page; null when none. Search
 * results (`q`) are not a place to return to: the menu goes back to the last view without
 * a search, such as the ranking that was open.
 */
export function memoryEntry(pathname: string, search: string): [string, string] | null {
  if (!(REMEMBERED_PAGES as readonly string[]).includes(pathname)) return null;
  if (new URLSearchParams(search).has("q")) return null;
  return [pathname, search ? `${pathname}?${search}` : pathname];
}

let cached: { raw: string | null; memory: Memory } = { raw: null, memory: {} };

function read(): Memory {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
    if (raw !== cached.raw) {
      const parsed: unknown = raw ? JSON.parse(raw) : {};
      cached = { raw, memory: parsed && typeof parsed === "object" ? (parsed as Memory) : {} };
    }
  } catch {
    // Storage blocked or bad JSON: remember nothing.
    cached = { raw, memory: {} };
  }
  return cached.memory;
}

export function remember(page: string, url: string): void {
  const memory = read();
  if (memory[page] === url) return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...memory, [page]: url }));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // Storage full or blocked: links keep their plain URLs.
  }
}

/** The remembered URL of `page`, or `page` itself. */
export function rememberedUrl(page: string): string {
  const url = read()[page];
  // Only same-page URLs: never follow something else that ended up in storage.
  return typeof url === "string" && (url === page || url.startsWith(`${page}?`)) ? url : page;
}

export function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}
