import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

import { allowlistFromEnv, isAllowedEmail } from "@/lib/auth/allowlist";

/**
 * Auth.js: Google OAuth, single-user allowlist (ALLOWED_EMAIL), JWT sessions.
 * Reads AUTH_SECRET, AUTH_GOOGLE_ID and AUTH_GOOGLE_SECRET from the environment.
 */
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  pages: { signIn: "/login", error: "/login" },
  session: { strategy: "jwt", maxAge: 60 * 60 * 24 * 14 },
  callbacks: {
    // Rejected sign-ins land on /login?error=AccessDenied.
    signIn({ profile }) {
      return profile?.email_verified === true && isAllowedEmail(profile.email, allowlistFromEnv());
    },
  },
});
