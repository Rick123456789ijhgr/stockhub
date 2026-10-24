/**
 * A page section without a frame (D-126): heading, an optional link or control on the right,
 * then the content. Panels (Card) are kept for things that are one unit, such as a stock's
 * quote header, a table or a chart.
 */
export function Section({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <header className="flex items-baseline justify-between gap-3 border-b pb-2">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {actions ? <div className="shrink-0 text-sm text-muted-foreground">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
