import "server-only";

import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { allowlistFromEnv, isAllowedEmail } from "@/lib/auth/allowlist";

export type CurrentUser = { email: string; name: string | null };

/**
 * The signed-in user, re-checked against the current allowlist (so removing an email
 * from ALLOWED_EMAIL revokes existing sessions). Null when not signed in or not allowed.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const session = await auth();
  const email = session?.user?.email;
  if (!email || !isAllowedEmail(email, allowlistFromEnv())) return null;
  return { email, name: session.user?.name ?? null };
}

/** For pages and server components: redirect to /login when there is no valid session. */
export async function requireUser(): Promise<CurrentUser> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}

/** For route handlers: a 401 response when there is no valid session. */
export async function requireApiUser(): Promise<CurrentUser | Response> {
  const user = await getCurrentUser();
  return user ?? Response.json({ error: "unauthorized" }, { status: 401 });
}
