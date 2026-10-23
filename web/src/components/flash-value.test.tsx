import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FlashValue } from "./flash-value";

function view(value: number | null) {
  return <FlashValue value={value}>price</FlashValue>;
}

describe("FlashValue", () => {
  afterEach(cleanup);

  it("flashes in the direction of a change, not on the first render", () => {
    const { rerender } = render(view(100));
    expect(screen.getByText("price").dataset.flash).toBeUndefined();
    rerender(view(101));
    expect(screen.getByText("price").dataset.flash).toBe("up");
    expect(screen.getByText("price").className).toContain("flash-up");
    rerender(view(99.5));
    expect(screen.getByText("price").dataset.flash).toBe("down");
  });

  it("does not flash when a value first appears or stays the same", () => {
    const { rerender } = render(view(null));
    rerender(view(100));
    expect(screen.getByText("price").dataset.flash).toBeUndefined();
    rerender(view(100));
    expect(screen.getByText("price").dataset.flash).toBeUndefined();
  });
});
