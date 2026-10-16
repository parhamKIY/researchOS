import { expect, test } from "vitest";
import { connectionMessage } from "../src/lib/system-llm";

test("unknown provider error details are never shown to administrators", () => {
  const message = connectionMessage({ error_code: "fixture-private-key-and-provider-body", outcome_unknown: false });
  expect(message).toBe("The connection test failed.");
  expect(message).not.toContain("private-key");
});

test("uncertain outcomes ask users to check provider usage before another test", () => {
  const message = connectionMessage({ error_code: "provider_outcome_unknown", outcome_unknown: true });
  expect(message).toContain("may have consumed quota");
  expect(message).toContain("before retrying");
  expect(connectionMessage({ error_code: "provider_authentication_failed", outcome_unknown: false })).toBe("The provider rejected the API key.");
});

test("access denial does not claim that the model ID is necessarily wrong", () => {
  const message = connectionMessage({ error_code: "provider_access_denied", outcome_unknown: false });
  expect(message).toContain("API permissions");
  expect(message).toContain("region");
  expect(message).not.toContain("This key does not have access to the selected model");
});
