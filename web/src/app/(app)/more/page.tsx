import { ChevronRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/coming-soon";
import { SECONDARY_ITEMS } from "@/components/nav/nav-items";
import { Card } from "@/components/ui/card";
import { SignOutButton } from "@/components/user-menu";

export const metadata: Metadata = { title: "更多" };

/** Mobile overflow menu for items that do not fit the bottom bar. */
export default function MorePage() {
  return (
    <>
      <PageHeader title="更多" />
      <Card className="py-0">
        <ul className="divide-y">
          {SECONDARY_ITEMS.map(({ href, label, icon: Icon }) => (
            <li key={href}>
              <Link href={href} className="flex min-h-12 items-center gap-3 px-4 text-sm">
                <Icon className="size-4 text-muted-foreground" aria-hidden />
                <span className="flex-1">{label}</span>
                <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
      <div className="mt-4">
        <SignOutButton withLabel />
      </div>
    </>
  );
}
