import "server-only";

import { redirect } from "next/navigation";
import { connection } from "next/server";

import { auth } from "@/auth";
import { allowlistFromEnv, isAllowedEmail } from "@/lib/auth/allowlist";
import { isAuthDisabled, LOCAL_USER } from "@/lib/auth/mode";

export type CurrentUser = { email: string; name: string | null };

/**
 * The signed-in user, re-checked against the current allowlist (so removing an email
 * from ALLOWED_EMAIL revokes existing sessions). Null when not signed in or not allowed.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  if (isAuthDisabled()) {
    // Like a real session read, the bypass must make the render request-time.
    await connection();
    return { ...LOCAL_USER };
  }
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
