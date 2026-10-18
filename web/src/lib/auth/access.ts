/**
 * Route protection policy used by src/proxy.ts. Everything is private except the login
 * page and Auth.js's own endpoints (CLAUDE.md rule 9).
 */

export type AccessDecision =
  | { type: "allow" }
  | { type: "redirect"; to: string }
  | { type: "unauthorized" };

const PUBLIC_PREFIXES = ["/api/auth/"];
const PUBLIC_PATHS = new Set(["/login", "/api/auth"]);

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname) || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

export function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

export function decideAccess(
  pathname: string,
  search: string,
  signedIn: boolean,
): AccessDecision {
  if (signedIn || isPublicPath(pathname)) return { type: "allow" };
  if (isApiPath(pathname)) return { type: "unauthorized" };
  const callbackUrl = encodeURIComponent(pathname + search);
  return { type: "redirect", to: pathname === "/" ? "/login" : `/login?callbackUrl=${callbackUrl}` };
}

/** Only same-origin relative paths are valid post-login targets (no open redirects). */
export function safeCallbackUrl(value: string | string[] | undefined): string {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return "/";
  }
  return candidate;
}
