import {
  Activity,
  ChartCandlestick,
  Ellipsis,
  Globe,
  History,
  House,
  ListFilter,
  type LucideIcon,
  Newspaper,
  Settings,
  Star,
  Wallet,
} from "lucide-react";

export type NavGroup = "main" | "tools" | "system";
export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  group: NavGroup;
  primary?: boolean;
};

/** Sidebar shows all items by group; the mobile bottom bar shows `primary` ones plus "更多". */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "首頁", icon: House, group: "main", primary: true },
  { href: "/portfolio", label: "持股", icon: Wallet, group: "main", primary: true },
  { href: "/stocks", label: "個股", icon: ChartCandlestick, group: "main", primary: true },
  { href: "/watchlist", label: "自選", icon: Star, group: "main" },
  { href: "/news", label: "新聞", icon: Newspaper, group: "main" },
  { href: "/market", label: "國際", icon: Globe, group: "main", primary: true },
  { href: "/screener", label: "篩選器", icon: ListFilter, group: "tools" },
  { href: "/backtest", label: "回測", icon: History, group: "tools" },
  { href: "/status", label: "狀態", icon: Activity, group: "system" },
  { href: "/admin", label: "設定", icon: Settings, group: "system" },
];

/** Group headings in the sidebar; the first group has none. */
export const NAV_GROUPS: { key: NavGroup; label: string | null }[] = [
  { key: "main", label: null },
  { key: "tools", label: "工具" },
  { key: "system", label: "系統" },
];

export const MORE_ITEM: NavItem = { href: "/more", label: "更多", icon: Ellipsis, group: "main" };

export const SECONDARY_ITEMS = NAV_ITEMS.filter((item) => !item.primary);

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** "更多" is highlighted while on it or on any page only reachable through it. */
export function isMoreActive(pathname: string): boolean {
  return (
    isActive(pathname, MORE_ITEM.href) ||
    SECONDARY_ITEMS.some((item) => isActive(pathname, item.href))
  );
}
