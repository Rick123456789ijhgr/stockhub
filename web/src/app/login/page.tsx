import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { signIn } from "@/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { safeCallbackUrl } from "@/lib/auth/access";
import { getCurrentUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "登入" };

/** Auth.js error codes (?error=...) shown on this page. */
const ERRORS: Record<string, string> = {
  AccessDenied: "這個 Google 帳號不在允許名單內，無法登入。若需要存取，請聯絡網站管理者。",
  Configuration: "伺服器的登入設定不完整，請檢查 AUTH_SECRET 與 Google OAuth 設定。",
  Verification: "登入連結已失效，請重新登入。",
};

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">StockHub</CardTitle>
          <CardDescription>個人台股研究平台，僅限授權帳號使用。</CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<Skeleton className="h-9 w-full" />}>
            <LoginForm searchParams={searchParams} />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}

async function LoginForm({ searchParams }: { searchParams: PageProps<"/login">["searchParams"] }) {
  const params = await searchParams;
  const callbackUrl = safeCallbackUrl(params.callbackUrl);
  if (await getCurrentUser()) redirect(callbackUrl);

  const errorCode = Array.isArray(params.error) ? params.error[0] : params.error;
  const error = errorCode ? (ERRORS[errorCode] ?? "登入失敗，請再試一次。") : null;
  const configured = Boolean(process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET);

  return (
    <div className="space-y-4">
      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {configured ? null : (
        <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
          尚未設定 Google OAuth（<code>AUTH_GOOGLE_ID</code>、<code>AUTH_GOOGLE_SECRET</code>）。
        </p>
      )}
      <form
        action={async () => {
          "use server";
          await signIn("google", { redirectTo: callbackUrl });
        }}
      >
        <Button type="submit" size="lg" className="w-full" disabled={!configured}>
          使用 Google 帳號登入
        </Button>
      </form>
    </div>
  );
}
