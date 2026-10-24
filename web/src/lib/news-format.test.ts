import { describe, expect, it } from "vitest";

import { hostOf, relativeTime, sentimentLabel, sentimentTone } from "./news-format";

describe("sentiment", () => {
  it("uses the ±0.3 cut-offs of the daily counts", () => {
    expect(sentimentTone(0.3)).toBe("up");
    expect(sentimentTone(0.29)).toBe("flat");
    expect(sentimentTone(-0.3)).toBe("down");
    expect(sentimentTone(null)).toBeNull();
    expect(sentimentTone(Number.NaN)).toBeNull();
  });

  it("labels the score with a word and sign", () => {
    expect(sentimentLabel(0.624)).toBe("偏多 +0.62");
    expect(sentimentLabel(-0.4)).toBe("偏空 −0.40");
    expect(sentimentLabel(0.1)).toBe("中性 +0.10");
    expect(sentimentLabel(0)).toBe("中性 ±0.00");
    expect(sentimentLabel(null)).toBeNull();
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-10-25T06:00:00Z"); // 14:00 Taipei
  it("counts minutes and hours within a day", () => {
    expect(relativeTime("2026-10-25T05:59:40Z", now)).toBe("剛剛");
    expect(relativeTime("2026-10-25T05:48:00Z", now)).toBe("12 分鐘前");
    expect(relativeTime("2026-10-25T03:00:00Z", now)).toBe("3 小時前");
  });

  it("shows the Taipei date and time after a day", () => {
    expect(relativeTime("2026-10-23T06:05:00Z", now)).toBe("10/23 14:05");
    // 17:00 UTC on 31 Dec is already 1 January in Taipei: this year, so no year shown.
    expect(relativeTime("2025-12-31T17:00:00Z", now)).toBe("01/01 01:00");
    expect(relativeTime("2025-06-01T00:00:00Z", now)).toBe("2025/06/01 08:00");
  });
});

describe("hostOf", () => {
  it("drops www and survives bad URLs", () => {
    expect(hostOf("https://www.ptt.cc/bbs/Stock/M.1.A.2.html")).toBe("ptt.cc");
    expect(hostOf("https://news.cnyes.com/news/id/1")).toBe("news.cnyes.com");
    expect(hostOf("not a url")).toBe("");
  });
});
