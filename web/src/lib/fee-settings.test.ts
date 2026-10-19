import { describe, expect, it } from "vitest";

import {
  describeFeeSettings,
  feeSettingsFromStored,
  parseFeeSettings,
} from "./fee-settings";
import { DEFAULT_FEES } from "./portfolio";

const valid = {
  rate: 0.001425,
  discount: 0.28,
  minFee: 20,
  minFeeOddLot: 1,
  discountMode: "rebate",
  rounding: "floor",
};

describe("parseFeeSettings", () => {
  it("accepts valid settings, numbers as strings too", () => {
    expect(parseFeeSettings(valid)).toEqual(valid);
    expect(parseFeeSettings({ ...valid, rate: "0.001425", minFee: "20" })).toEqual(valid);
  });

  it.each([
    ["rate", 0],
    ["rate", 0.02],
    ["discount", 0],
    ["discount", 1.1],
    ["minFee", 1.5],
    ["minFee", -1],
    ["minFeeOddLot", 5000],
    ["discountMode", "later"],
    ["rounding", "ceil"],
    ["rate", ""],
  ])("rejects %s = %s", (key, value) => {
    expect(parseFeeSettings({ ...valid, [key]: value })).toBeNull();
  });

  it("falls back to the defaults for a missing or broken stored value", () => {
    expect(feeSettingsFromStored(undefined)).toEqual(DEFAULT_FEES);
    expect(feeSettingsFromStored({ rate: "x" })).toEqual(DEFAULT_FEES);
  });
});

describe("describeFeeSettings", () => {
  it("summarizes discount, minimums and mode", () => {
    expect(describeFeeSettings(parseFeeSettings(valid)!)).toBe(
      "0.1425% × 2.8 折，最低 20 元（零股 1 元），先收全額，事後退還，元以下捨去",
    );
    expect(describeFeeSettings(DEFAULT_FEES)).toBe("0.1425%，最低 20 元（零股 1 元），元以下捨去");
  });
});
