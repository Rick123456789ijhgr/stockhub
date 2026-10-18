import { LogOut } from "lucide-react";

import { signOut } from "@/auth";
import { Button } from "@/components/ui/button";
import { isAuthDisabled } from "@/lib/auth/mode";
import { getCurrentUser } from "@/lib/auth/session";

export async function UserMenu() {
  const user = await getCurrentUser();
  if (!user) return null;
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="truncate text-xs text-muted-foreground" title={user.email}>
        {user.email}
      </span>
      {isAuthDisabled() ? null : <SignOutButton />}
    </div>
  );
}

export function SignOutButton({ withLabel = false }: { withLabel?: boolean }) {
  return (
    <form
      action={async () => {
        "use server";
        await signOut({ redirectTo: "/login" });
      }}
    >
      <Button
        type="submit"
        variant="ghost"
        size={withLabel ? "default" : "icon-sm"}
        aria-label="登出"
      >
        <LogOut aria-hidden />
        {withLabel ? "登出" : null}
      </Button>
    </form>
  );
}
