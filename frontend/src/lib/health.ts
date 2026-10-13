export type HealthState = "checking" | "ok" | "unavailable";

export async function readHealth(path: string, signal: AbortSignal): Promise<HealthState> {
  try {
    const response = await fetch(path, { cache: "no-store", signal });
    const body: unknown = await response.json();
    if (
      response.ok && body !== null && typeof body === "object" &&
      "status" in body && body.status === "ok"
    ) return "ok";
  } catch {
    // Connection, timeout, and malformed responses all leave readiness unconfirmed.
  }
  return "unavailable";
}
