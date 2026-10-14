export type SystemAdapter = "gemini" | "openai_compatible" | "mock";
export type SystemModel = {
  id: string; adapter: SystemAdapter; model_name: string;
  parameters: { temperature?: number; max_output_tokens?: number };
  execution_mode: "live" | "mock"; state: string; checked_at: string | null;
};
export type SystemCheck = SystemModel & {
  base_url: string | null; credential_configured: boolean; error_code: string | null;
  outcome_unknown: boolean; total_tokens: number | null; latency_ms: number | null; created_at: string;
};
export type SystemSettings = { revision: number; etag: string; active: SystemCheck | null; checks: SystemCheck[] };
export type PublicSystemSettings = { active: SystemModel | null };
export type ApplyResult = { applied: boolean; check: SystemCheck; settings: SystemSettings };
export const geminiBase = "https://generativelanguage.googleapis.com/v1beta";

export function connectionMessage(check: Pick<SystemCheck, "error_code" | "outcome_unknown">): string {
  const messages: Record<string, string> = {
    provider_authentication_failed: "The provider rejected the API key.",
    provider_access_denied: "This key does not have access to the selected model.",
    model_unavailable: "The model or API endpoint was not found.",
    provider_request_rejected: "The provider rejected the request. Check the model, API base URL and parameter support.",
    provider_address_rejected: "The endpoint did not resolve exclusively to public network addresses.",
    provider_dns_failed: "The provider hostname could not be resolved.",
    provider_connection_failed: "A secure connection to the provider could not be established.",
    provider_rate_limited: "The provider rate limit or quota was reached.",
    provider_content_blocked: "The provider did not return a usable text response.",
    provider_empty_response: "The provider returned no text.",
    provider_invalid_response: "The response did not match the selected API protocol.",
    probe_interrupted: "The server interrupted this connection test.",
    stale_revision: "Settings changed during the test. Reload and test again.",
    admin_access_changed: "Administrator access changed during the test.",
  };
  const message = messages[check.error_code ?? ""] ?? "The connection test failed.";
  return check.outcome_unknown ? `${message} The request may have consumed quota; check your provider before retrying.` : message;
}
