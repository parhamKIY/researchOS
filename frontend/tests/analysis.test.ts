import { expect, test } from "vitest";
import { analysisBody, isMockReport, type AnalysisPlan } from "../src/lib/analysis";

test("analysis consent pins exact reviewed destinations and preserves retry acknowledgments", () => {
  const plan = { fingerprint: "reviewed-fingerprint", targets: [{ configuration_id: "fallback" }, { configuration_id: "primary" }, { configuration_id: "primary" }] } as AnalysisPlan;
  const payload = JSON.parse(analysisBody(plan, "owned-version", "fa", true, "failed-report", true));
  expect(payload.approved_configuration_ids).toEqual(["fallback", "primary"]);
  expect(payload.document_version_id).toBe("owned-version");
  expect(payload.plan_fingerprint).toBe("reviewed-fingerprint");
  expect(payload.retry_of_id).toBe("failed-report");
  expect(payload.acknowledge_unknown_outcome).toBe(true);
});

test("a mixed route must not be presented as an entirely local mock report", () => {
  expect(isMockReport({ configuration: { routes: { task: [{ execution_mode: "mock" }, { execution_mode: "live" }] } } } as never)).toBe(false);
  expect(isMockReport({ configuration: { routes: { task: [{ execution_mode: "mock" }] } } } as never)).toBe(true);
});
