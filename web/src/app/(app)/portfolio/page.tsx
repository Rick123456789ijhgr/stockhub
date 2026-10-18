import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

import { PLACEHOLDERS } from "../placeholders";

const page = PLACEHOLDERS.portfolio;

export const metadata: Metadata = { title: page.title };

export default function PortfolioPage() {
  return <ComingSoon title={page.title} milestone={page.milestone} features={[...page.features]} />;
}
