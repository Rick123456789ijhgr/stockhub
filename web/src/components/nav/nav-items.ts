import {
  Activity,
  ChartCandlestick,
  Ellipsis,
  Globe,
  History,
  House,
  ListFilter,
  type LucideIcon,
  Settings,
  Star,
  Wallet,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; primary?: boolean };

/** Sidebar shows all items; the mobile bottom bar shows `primary` ones plus "更多". */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "首頁", icon: House, primary: true },
  { href: "/portfolio", label: "持股", icon: Wallet, primary: true },
  { href: "/stocks", label: "個股", icon: ChartCandlestick, primary: true },
  { href: "/watchlist", label: "自選", icon: Star },
  { href: "/market", label: "市場", icon: Globe, primary: true },
  { href: "/screener", label: "篩選器", icon: ListFilter },
  { href: "/backtest", label: "回測", icon: History },
  { href: "/status", label: "狀態", icon: Activity },
  { href: "/admin", label: "設定", icon: Settings },
];

export const MORE_ITEM: NavItem = { href: "/more", label: "更多", icon: Ellipsis };

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
