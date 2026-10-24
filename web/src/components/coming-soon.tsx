import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Page title, its one-line description and optional actions on the right (D-125). */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-x-4 gap-y-2 md:mb-6">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Placeholder for pages that later milestones fill in. */
export function ComingSoon({
  title,
  milestone,
  features,
}: {
  title: string;
  milestone: string;
  features: string[];
}) {
  return (
    <>
      <PageHeader title={title} />
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>即將推出</CardTitle>
            <Badge variant="secondary">{milestone}</Badge>
          </div>
          <CardDescription>這個頁面會在 {milestone} 建置，預計包含：</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {features.map((feature) => (
              <li key={feature}>{feature}</li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
