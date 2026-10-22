import { describe, expect, it } from "vitest";

import { isAuthDisabled, isLocalMachine } from "./mode";

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

  it("is on in the production build stockhub.bat starts on this machine", () => {
    const local = { AUTH_DISABLED: "true", NODE_ENV: "production", STOCKHUB_LOCAL_SERVER: "true" };
    expect(isAuthDisabled(env(local))).toBe(true);
    expect(isAuthDisabled(env({ ...local, STOCKHUB_LOCAL_SERVER: "1" }))).toBe(false);
    expect(isAuthDisabled(env({ ...local, VERCEL: "1" }))).toBe(false);
  });
});

describe("isLocalMachine", () => {
  const env = (vars: Record<string, string>) => vars as unknown as NodeJS.ProcessEnv;

  it("is never true on Vercel", () => {
    expect(isLocalMachine(env({ NODE_ENV: "development", VERCEL: "1" }))).toBe(false);
    expect(
      isLocalMachine(env({ NODE_ENV: "production", STOCKHUB_LOCAL_SERVER: "true", VERCEL: "1" })),
    ).toBe(false);
  });

  it("needs the launcher's flag in production", () => {
    expect(isLocalMachine(env({ NODE_ENV: "production" }))).toBe(false);
    expect(isLocalMachine(env({ NODE_ENV: "production", STOCKHUB_LOCAL_SERVER: "true" }))).toBe(true);
    expect(isLocalMachine(env({ NODE_ENV: "development" }))).toBe(true);
  });
});
