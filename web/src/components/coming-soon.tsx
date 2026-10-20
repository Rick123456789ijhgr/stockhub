import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-3 md:mb-4">
      <h1 className="text-lg font-semibold tracking-tight md:text-xl">{title}</h1>
      {description ? <p className="mt-0.5 text-sm text-muted-foreground">{description}</p> : null}
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
