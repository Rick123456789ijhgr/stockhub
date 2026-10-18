import { describe, expect, it } from "vitest";

import { isAllowedEmail, parseAllowlist } from "./allowlist";

describe("allowlist", () => {
  it("parses comma-separated emails case-insensitively", () => {
    const list = parseAllowlist(" Me@Example.com, other@example.com ,,");
    expect([...list]).toEqual(["me@example.com", "other@example.com"]);
    expect(isAllowedEmail("ME@example.COM", list)).toBe(true);
    expect(isAllowedEmail(" other@example.com ", list)).toBe(true);
  });

  it("rejects everyone else", () => {
    const list = parseAllowlist("me@example.com");
    expect(isAllowedEmail("intruder@example.com", list)).toBe(false);
    expect(isAllowedEmail("me@example.com.evil.com", list)).toBe(false);
    expect(isAllowedEmail(null, list)).toBe(false);
    expect(isAllowedEmail("", list)).toBe(false);
  });

  it("treats an empty or missing allowlist as nobody", () => {
    expect(isAllowedEmail("me@example.com", parseAllowlist(""))).toBe(false);
    expect(isAllowedEmail("me@example.com", parseAllowlist(undefined))).toBe(false);
  });
});
