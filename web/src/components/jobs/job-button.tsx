"use client";

import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import type { RequestableJob } from "@/lib/job-request-input";

type Queued = { id: string; duplicate: boolean; runner: "started" | "queued" };

/**
 * Queues a data job (POST /api/jobs) and refreshes the page, whose request list then shows
 * its progress. Several requests in `requests` are queued one after another.
 */
export function JobButton({
  requests,
  label,
  variant = "outline",
  size = "sm",
}: {
  requests: { job: RequestableJob; params?: Record<string, string> }[];
  label: string;
  variant?: "outline" | "default" | "secondary" | "ghost";
  size?: "xs" | "sm" | "default";
}) {
  const router = useRouter();
  const queue = useMutation({
    mutationFn: async () => {
      let last: Queued | null = null;
      for (const r of requests) {
        const response = await fetch("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job: r.job, params: r.params ?? {} }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        last = (await response.json()) as Queued;
      }
      return last;
    },
    onSuccess: () => router.refresh(),
  });
  const note = queue.isError
    ? "送出失敗，請再試一次"
    : queue.data?.runner === "queued"
      ? "已排入，下次排程時執行"
      : queue.isSuccess
        ? "已開始執行"
        : null;

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        type="button"
        variant={variant}
        size={size}
        disabled={queue.isPending || requests.length === 0}
        onClick={() => queue.mutate()}
      >
        <RefreshCw className={queue.isPending ? "animate-spin" : undefined} aria-hidden />
        {label}
      </Button>
      {note ? (
        <span className="text-xs text-muted-foreground" role="status">
          {note}
        </span>
      ) : null}
    </span>
  );
}
