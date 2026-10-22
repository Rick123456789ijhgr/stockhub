/**
 * The app runs on this machine for its single user: never on Vercel, and either in
 * development or as the production build stockhub.bat starts bound to 127.0.0.1 (it sets
 * STOCKHUB_LOCAL_SERVER=true itself; the variable does not belong in .env). See
 * docs/DECISIONS.md D-041 and D-117.
 */
export function isLocalMachine(env: NodeJS.ProcessEnv = process.env): boolean {
  if (env.VERCEL) return false;
  return env.NODE_ENV !== "production" || env.STOCKHUB_LOCAL_SERVER === "true";
}

/**
 * Local-only auth bypass (docs/DECISIONS.md D-041). Honoured only when AUTH_DISABLED=true
 * on this machine (`isLocalMachine`), so a deployed site can never be opened without a
 * session even if the variable leaks into its settings.
 */
export function isAuthDisabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.AUTH_DISABLED === "true" && isLocalMachine(env);
}

export const LOCAL_USER = { email: "local@localhost", name: "本機模式" } as const;
