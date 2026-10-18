/** Email allowlist from ALLOWED_EMAIL (comma-separated, case-insensitive). Empty = nobody. */
export function parseAllowlist(raw: string | undefined | null): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isAllowedEmail(
  email: string | null | undefined,
  allowlist: ReadonlySet<string>,
): boolean {
  if (!email) return false;
  return allowlist.has(email.trim().toLowerCase());
}

export function allowlistFromEnv(): Set<string> {
  return parseAllowlist(process.env.ALLOWED_EMAIL);
}
