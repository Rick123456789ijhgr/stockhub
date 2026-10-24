/**
 * Which links get the stock hover preview (D-132) and where it opens. Pure, so the rules are
 * tested without a browser.
 */

export const PREVIEW_WIDTH = 248;
export const PREVIEW_HEIGHT = 184;
const GAP = 8;
const MARGIN = 8;

/**
 * The symbol a link points to, when it is a stock page of this site (`/stocks/2330`, any
 * query) and not the page already open; else null.
 */
export function previewSymbol(href: string, current: { origin: string; pathname: string }): string | null {
  let url: URL;
  try {
    url = new URL(href, current.origin);
  } catch {
    return null;
  }
  if (url.origin !== current.origin) return null;
  const match = /^\/stocks\/([^/]+)\/?$/.exec(url.pathname);
  if (!match) return null;
  if (url.pathname.replace(/\/$/, "") === current.pathname.replace(/\/$/, "")) return null;
  try {
    return decodeURIComponent(match[1]!);
  } catch {
    return null;
  }
}

/**
 * Top-left corner for the preview: below the link, or above it when there is no room below;
 * aligned with the link's left edge and kept inside the viewport.
 */
export function previewPosition(
  link: { left: number; top: number; bottom: number },
  viewport: { width: number; height: number },
): { left: number; top: number; above: boolean } {
  const above = link.bottom + GAP + PREVIEW_HEIGHT > viewport.height - MARGIN && link.top - GAP - PREVIEW_HEIGHT >= MARGIN;
  const top = above ? link.top - GAP - PREVIEW_HEIGHT : link.bottom + GAP;
  const left = Math.min(Math.max(link.left, MARGIN), Math.max(MARGIN, viewport.width - PREVIEW_WIDTH - MARGIN));
  return { left, top, above };
}
