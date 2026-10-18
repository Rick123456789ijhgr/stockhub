import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PriceChange } from "./price-change";

describe("PriceChange", () => {
  it("uses semantic up/down tokens, not literal colors", () => {
    render(
      <>
        <PriceChange value={1.234} suffix="%" />
        <PriceChange value="-0.5" />
        <PriceChange value={0} />
      </>,
    );
    const up = screen.getByText("▲1.23%");
    const down = screen.getByText("▼0.50");
    const flat = screen.getByText("0.00");
    expect(up).toHaveClass("text-up");
    expect(up).toHaveAttribute("data-direction", "up");
    expect(down).toHaveClass("text-down");
    expect(flat).toHaveClass("text-flat");
    for (const el of [up, down, flat]) {
      expect(el.className).not.toMatch(/red|green/);
    }
  });
});
