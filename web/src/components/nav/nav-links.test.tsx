import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SidebarNavList } from "./nav-links";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useSearchParams: () => new URLSearchParams() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.ComponentProps<"a">) => (
    <a href={href} {...props} onClick={(e) => { e.preventDefault(); props.onClick?.(e); }}>
      {children}
    </a>
  ),
  useLinkStatus: () => ({ pending: false }),
}));

const highlight = () => screen.getByRole("navigation").getAttribute("data-highlight");

describe("SidebarNavList highlight", () => {
  afterEach(cleanup);

  it("jumps to a clicked item, then follows the page that loads", () => {
    const { rerender } = render(<SidebarNavList pathname="/stocks" />);
    expect(highlight()).toBe("/stocks");
    fireEvent.click(screen.getByText("首頁"));
    expect(highlight()).toBe("/");
    rerender(<SidebarNavList pathname="/" />);
    expect(highlight()).toBe("/");
  });

  it("forgets an old click once another page has loaded", () => {
    // 個股 → 首頁 (nav click) → a stock from the home page → back to 個股.
    const { rerender } = render(<SidebarNavList pathname="/stocks" />);
    fireEvent.click(screen.getByText("首頁"));
    rerender(<SidebarNavList pathname="/" />);
    rerender(<SidebarNavList pathname="/stocks/2330" />);
    rerender(<SidebarNavList pathname="/stocks" />);
    expect(highlight()).toBe("/stocks");
  });
});
