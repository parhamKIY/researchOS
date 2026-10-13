import { afterEach, describe, expect, it, vi } from "vitest";
import { readHealth } from "../src/lib/health";

afterEach(() => vi.unstubAllGlobals());
const signal = () => new AbortController().signal;

describe("health response trust", () => {
  it("accepts an explicit successful readiness response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"status":"ok"}')));
    expect(await readHealth("/api/v1/health/ready", signal())).toBe("ok");
  });
  it("does not report ready when the server returns a failure status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 503 })));
    expect(await readHealth("/api/v1/health/ready", signal())).toBe("unavailable");
  });
  it("does not report ready for malformed or disconnected responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('<html>proxy error</html>')));
    expect(await readHealth("/api/v1/health/ready", signal())).toBe("unavailable");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(await readHealth("/api/v1/health/ready", signal())).toBe("unavailable");
  });
});
