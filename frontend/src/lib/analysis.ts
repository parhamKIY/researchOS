export type Destination = { configuration_id: string; source: string; model_name: string; adapter: string; base_url: string | null; execution_mode: "mock" | "live" };
export type AnalysisPlan = { fingerprint: string; targets: Destination[]; external_required: boolean; external_processing_allowed: boolean; snapshot: { coverage: string; included_chunks: number; total_chunks: number } };
export type Witness = { page_id: string; page_number: number; start_offset: number; end_offset: number; quote: string; section_ids: string[] };
export type Claim = { kind: "author_claim" | "supported_interpretation" | "ai_suggestion"; topic: string; text: string; evidence: Witness[]; result: Record<string, string | null> | null; resource: { name: string; url: string | null; verification: string } | null };
export type ReportPart = { kind: string; state: string; error_code: string | null; payload: { items: Claim[]; unavailable_reason: string | null; generation: { execution_mode: string; model_name: string; configuration_id: string; attempt_id: string } } | null };
export type Report = { id: string; state: string; language: "fa" | "en"; progress: number; stage: string | null; error_code: string | null; outcome_unknown: boolean; document_version_id: string; retry_of_id: string | null; created_at: string; configuration: { parser_name: string; parser_version: string; prompt_version: string; schema_version: string; coverage: string; included_chunks: number; total_chunks: number; extraction_warnings: string[]; routes: Record<string, Destination[]> }; sections: ReportPart[]; usage: { id: string; section: string; model_name: string; state: string; execution_mode: string; total_tokens: number | null; latency_ms: number | null }[] };
export const analysisSections = ["overview", "methodology", "results", "limitations", "future_work", "research_gaps", "resources"];
export const claimLabels = { author_claim: "Author claim · interpretation has not been independently verified", supported_interpretation: "AI interpretation · inspect supporting evidence", ai_suggestion: "AI suggestion · novelty and feasibility unverified" };

export function analysisBody(plan: AnalysisPlan, version: string, language: string, external: boolean, retry: string | null, unknown: boolean) {
  return JSON.stringify({ document_version_id: version, language, plan_fingerprint: plan.fingerprint,
    approved_configuration_ids: [...new Set(plan.targets.map((target) => target.configuration_id))].sort(),
    acknowledge_external_processing: external, retry_of_id: retry, acknowledge_unknown_outcome: unknown });
}

export function isMockReport(report: Pick<Report, "configuration">) {
  return Object.values(report.configuration.routes).flat().every((target) => target.execution_mode === "mock");
}
