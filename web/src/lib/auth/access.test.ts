import { describe, expect, it } from "vitest";

import { decideAccess, isPublicPath, safeCallbackUrl } from "./access";

describe("decideAccess", () => {
  it("lets signed-in users through everywhere", () => {
    expect(decideAccess("/status", "", true)).toEqual({ type: "allow" });
    expect(decideAccess("/api/status", "", true)).toEqual({ type: "allow" });
  });

  it("redirects anonymous page requests to /login with a callback", () => {
    expect(decideAccess("/", "", false)).toEqual({ type: "redirect", to: "/login" });
    expect(decideAccess("/status", "?x=1", false)).toEqual({
      type: "redirect",
      to: "/login?callbackUrl=%2Fstatus%3Fx%3D1",
    });
  });

  it("answers anonymous API requests with 401", () => {
    expect(decideAccess("/api/status", "", false)).toEqual({ type: "unauthorized" });
    expect(decideAccess("/api", "", false)).toEqual({ type: "unauthorized" });
  });

  it("keeps only the login page and Auth.js endpoints public", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/api/auth/callback/google")).toBe(true);
    expect(isPublicPath("/api/auth/session")).toBe(true);
    expect(isPublicPath("/login/extra")).toBe(false);
    expect(isPublicPath("/api/authx")).toBe(false);
    expect(isPublicPath("/admin")).toBe(false);
    expect(decideAccess("/login", "", false)).toEqual({ type: "allow" });
  });
});

describe("safeCallbackUrl", () => {
  it.each([
    [undefined, "/"],
    ["/status", "/status"],
    ["/status?x=1", "/status?x=1"],
    [["/admin", "/x"], "/admin"],
    ["https://evil.example", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeCallbackUrl(input)).toBe(expected);
  });
});
