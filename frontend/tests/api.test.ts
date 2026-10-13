import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/lib/api";

afterEach(() => vi.unstubAllGlobals());

test("mutations use same-origin cookies and session CSRF", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  await api("/auth/logout", { method: "POST" }, "session-csrf");
  const [path, options] = fetcher.mock.calls[0];
  expect(path).toBe("/api/v1/auth/logout");
  expect(options.credentials).toBe("same-origin");
  expect(options.headers.get("X-CSRF-Token")).toBe("session-csrf");
});

test("API errors preserve authentication status for session recovery", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Sign in" } }), { status: 401 })));
  await expect(api("/auth/session")).rejects.toMatchObject({ status: 401, message: "Sign in" });
});

test("network failure cannot masquerade as successful logout", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(api("/auth/logout", { method: "POST" })).rejects.toMatchObject({ status: 0 });
});
