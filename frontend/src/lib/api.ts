export type Session = { user: { id: string; email: string; is_admin: boolean }; expires_at: string; csrf_token: string };

export class ApiFailure extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if (typeof options.body === "string") headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options, headers, credentials: "same-origin", cache: "no-store",
      signal: options.signal ?? AbortSignal.timeout(30000),
    });
  } catch {
    throw new ApiFailure(0, "Could not reach the server. Please try again.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiFailure(response.status, payload?.error?.message ?? "The request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
