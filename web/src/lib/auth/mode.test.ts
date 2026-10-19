import { describe, expect, it } from "vitest";

import { isAuthDisabled } from "./mode";

describe("isAuthDisabled", () => {
  const env = (vars: Record<string, string>) => vars as unknown as NodeJS.ProcessEnv;

  it("is on only when explicitly enabled in local development", () => {
    expect(isAuthDisabled(env({ AUTH_DISABLED: "true", NODE_ENV: "development" }))).toBe(true);
    expect(isAuthDisabled(env({ AUTH_DISABLED: "1", NODE_ENV: "development" }))).toBe(false);
    expect(isAuthDisabled(env({ NODE_ENV: "development" }))).toBe(false);
  });

  it("can never be on in production or on Vercel", () => {
    expect(isAuthDisabled(env({ AUTH_DISABLED: "true", NODE_ENV: "production" }))).toBe(false);
    expect(
      isAuthDisabled(env({ AUTH_DISABLED: "true", NODE_ENV: "development", VERCEL: "1" })),
    ).toBe(false);
  });
});
