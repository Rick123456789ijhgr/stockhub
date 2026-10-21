/** JSON request for the admin editors; a non-2xx answer throws the route's `error` message. */
export async function sendJson(method: string, url: string, body?: unknown): Promise<void> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(data?.error ?? `HTTP ${response.status}`);
  }
}
