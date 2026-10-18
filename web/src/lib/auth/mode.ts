/**
 * Local-only auth bypass (docs/DECISIONS.md D-041). Honoured only when AUTH_DISABLED=true
 * AND the app is not running on Vercel AND not in production mode, so a deployed site can
 * never be opened without a session even if the variable leaks into its settings.
 */
export function isAuthDisabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.AUTH_DISABLED === "true" && !env.VERCEL && env.NODE_ENV !== "production";
}

export const LOCAL_USER = { email: "local@localhost", name: "本機模式" } as const;
