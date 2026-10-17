import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { decideAccess } from "@/lib/auth/access";
import { allowlistFromEnv, isAllowedEmail } from "@/lib/auth/allowlist";

/**
 * Next.js 16 proxy (formerly middleware): every route and /api/* requires a session,
 * except /login and Auth.js endpoints. Pages and route handlers re-check the session
 * themselves (lib/auth/session.ts); this is the first gate, not the only one.
 */
export const proxy = auth((req) => {
  const email = req.auth?.user?.email;
  const signedIn = isAllowedEmail(email, allowlistFromEnv());
  const decision = decideAccess(req.nextUrl.pathname, req.nextUrl.search, signedIn);
  if (decision.type === "unauthorized") {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (decision.type === "redirect") {
    return NextResponse.redirect(new URL(decision.to, req.nextUrl.origin));
  }
  return NextResponse.next();
});

export const config = {
  // Everything except Next.js build assets and static files in public/.
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt)$).*)"],
};
