/**
 * Remounts on every page change (not on `?tab=` changes), so each page's content eases in
 * once (`.page-enter`, globals.css; off under prefers-reduced-motion). D-125.
 */
export default function AppTemplate({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
