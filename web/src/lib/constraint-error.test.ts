import { describe, expect, it } from "vitest";

import { constraintMessage, reviewResponse } from "./constraint-error";

describe("constraintMessage", () => {
  it("explains check, not-null and range violations only", () => {
    expect(constraintMessage({ code: "23514" })).toContain("無法採用");
    expect(constraintMessage({ code: "23502" })).toContain("必要欄位");
    expect(constraintMessage({ code: "40001" })).toBeNull();
    expect(constraintMessage(new Error("x"))).toBeNull();
    expect(constraintMessage(null)).toBeNull();
  });
});

describe("reviewResponse", () => {
  it("maps outcomes to responses and rethrows other errors", async () => {
    expect((await reviewResponse(async () => true)).status).toBe(200);
    expect((await reviewResponse(async () => false)).status).toBe(409);
    const blocked = await reviewResponse(async () => {
      throw Object.assign(new Error("check"), { code: "23514" });
    });
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { error: string }).error).toContain("只能捨棄");
    await expect(reviewResponse(async () => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
  });
});
