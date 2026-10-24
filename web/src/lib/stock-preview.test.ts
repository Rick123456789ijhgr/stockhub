import { describe, expect, it } from "vitest";

import { PREVIEW_HEIGHT, previewPosition, previewSymbol } from "./stock-preview";

const here = { origin: "http://127.0.0.1:3000", pathname: "/" };

describe("previewSymbol", () => {
  it("finds the symbol of stock page links", () => {
    expect(previewSymbol("/stocks/2330", here)).toBe("2330");
    expect(previewSymbol("http://127.0.0.1:3000/stocks/00631L?tab=chips", here)).toBe("00631L");
    expect(previewSymbol("/stocks/2330/", here)).toBe("2330");
  });

  it("skips other links", () => {
    expect(previewSymbol("/stocks", here)).toBeNull();
    expect(previewSymbol("/stocks?tab=volume", here)).toBeNull();
    expect(previewSymbol("/portfolio", here)).toBeNull();
    expect(previewSymbol("https://example.com/stocks/2330", here)).toBeNull();
  });

  it("skips links to the stock page already open (its own tabs)", () => {
    const onPage = { ...here, pathname: "/stocks/2330" };
    expect(previewSymbol("/stocks/2330?tab=chips", onPage)).toBeNull();
    expect(previewSymbol("/stocks/2317", onPage)).toBe("2317");
  });
});

describe("previewPosition", () => {
  const viewport = { width: 1440, height: 900 };

  it("opens below the link, aligned to its left edge", () => {
    expect(previewPosition({ left: 300, top: 100, bottom: 120 }, viewport)).toEqual({ left: 300, top: 128, above: false });
  });

  it("opens above when there is no room below", () => {
    const p = previewPosition({ left: 300, top: 850, bottom: 870 }, viewport);
    expect(p).toEqual({ left: 300, top: 850 - 8 - PREVIEW_HEIGHT, above: true });
  });

  it("stays inside the viewport horizontally", () => {
    expect(previewPosition({ left: 1400, top: 100, bottom: 120 }, viewport).left).toBe(1440 - 248 - 8);
    expect(previewPosition({ left: -20, top: 100, bottom: 120 }, viewport).left).toBe(8);
  });
});
