import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ current: null as { user: { email: string } } | null }));

// Replace Auth.js's wrapper with one that injects a controllable session.
vi.mock("@/auth", () => ({
  auth:
    (handler: (req: NextRequest & { auth: unknown }) => Response) =>
    (req: NextRequest) =>
      handler(Object.assign(req, { auth: session.current })),
}));

const { proxy, config } = await import("./proxy");

function call(path: string): Response {
  const handler = proxy as unknown as (req: NextRequest) => Response;
  return handler(new NextRequest(new URL(path, "http://localhost:3000")));
}

describe("proxy", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("ALLOWED_EMAIL", "me@example.com");
    session.current = null;
  });

  it("redirects anonymous page requests to /login", () => {
    const res = call("/status");
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?callbackUrl=%2Fstatus");
  });

  it("rejects anonymous API requests with 401 JSON", async () => {
    const res = call("/api/status");
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "unauthorized" });
  });

  it("allows the login page and Auth.js endpoints without a session", () => {
    expect(call("/login").headers.get("x-middleware-next")).toBe("1");
    expect(call("/api/auth/signin").headers.get("x-middleware-next")).toBe("1");
  });

  it("allows allowlisted users", () => {
    session.current = { user: { email: "me@example.com" } };
    expect(call("/status").headers.get("x-middleware-next")).toBe("1");
    expect(call("/api/status").headers.get("x-middleware-next")).toBe("1");
  });

  it("treats a session whose email left the allowlist as anonymous", () => {
    session.current = { user: { email: "former@example.com" } };
    expect(call("/api/status").status).toBe(401);
  });

  it("lets everything through when the local auth bypass is on", () => {
    vi.stubEnv("AUTH_DISABLED", "true");
    expect(call("/api/status").headers.get("x-middleware-next")).toBe("1");
    vi.stubEnv("VERCEL", "1");
    expect(call("/api/status").status).toBe(401);
  });

  it.each(["/", "/status", "/admin", "/api/status", "/api/auth/session", "/login"])(
    "runs on %s",
    (url) => {
      expect(unstable_doesMiddlewareMatch({ config, url })).toBe(true);
    },
  );

  it.each(["/_next/static/chunks/app.js", "/_next/image?url=x", "/favicon.ico"])(
    "skips static asset %s",
    (url) => {
      expect(unstable_doesMiddlewareMatch({ config, url })).toBe(false);
    },
  );
});
