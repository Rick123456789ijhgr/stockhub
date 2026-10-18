import { PageHeader } from "@/components/coming-soon";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const SECTIONS = [
  { title: "持股損益與今日漲跌", milestone: "M2" },
  { title: "大盤與國際市場", milestone: "M1 / M5" },
  { title: "重大新聞與警示", milestone: "M6" },
  { title: "三大法人買賣超排行", milestone: "M4" },
];

export default function HomePage() {
  return (
    <>
      <PageHeader title="首頁" description="各區塊會隨里程碑逐步上線。" />
      <div className="grid gap-3 md:grid-cols-2">
        {SECTIONS.map((section) => (
          <Card key={section.title}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                {section.title}
                <Badge variant="secondary">{section.milestone}</Badge>
              </CardTitle>
              <CardDescription>即將推出</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </>
  );
}
