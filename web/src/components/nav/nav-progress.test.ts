import { afterEach, describe, expect, it } from "vitest";

import { navigationTarget } from "./nav-progress";

function click(html: string, init: MouseEventInit = {}): string | null {
  document.body.innerHTML = html;
  const target = document.querySelector("[data-click]") ?? document.querySelector("a")!;
  let result: string | null = null;
  const listener = (event: MouseEvent) => {
    result = navigationTarget(event, window.location);
    event.preventDefault(); // keep jsdom from navigating
  };
  document.addEventListener("click", listener);
  target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ...init }));
  document.removeEventListener("click", listener);
  return result;
}

describe("navigationTarget", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("returns the in-app path and query of a clicked link", () => {
    expect(click('<a href="/stocks/2330?tab=chips">x</a>')).toBe("/stocks/2330?tab=chips");
    expect(click('<a href="/watchlist"><span data-click>自選</span></a>')).toBe("/watchlist");
  });

  it("ignores clicks that do not navigate here", () => {
    expect(click(`<a href="${window.location.pathname}">same</a>`)).toBeNull();
    expect(click('<a href="https://example.com/">out</a>')).toBeNull();
    expect(click('<a href="/x" target="_blank">tab</a>')).toBeNull();
    expect(click('<a href="/x" download>file</a>')).toBeNull();
    expect(click('<a href="/x">new tab</a>', { ctrlKey: true })).toBeNull();
    expect(click('<a href="/x">middle</a>', { button: 1 })).toBeNull();
    expect(click('<button data-click>not a link</button>')).toBeNull();
  });
});
