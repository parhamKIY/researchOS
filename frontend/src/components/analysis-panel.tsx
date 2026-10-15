"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";
import { analysisBody, analysisSections, claimLabels, isMockReport, type AnalysisPlan, type Report, type Witness } from "@/lib/analysis";
import { evidenceParts } from "@/lib/evidence";

type ReportPage = { items: Report[]; next_cursor: string | null };
type PaperPrivacy = { id: string; revision: number; external_processing_allowed: boolean };

export function AnalysisPanel({ paperId, versionId, ready, session, expired, sourcePage }: { paperId: string; versionId: string; ready: boolean; session: Session; expired: () => void; sourcePage: (page: number) => void }) {
  const [history, setHistory] = useState<Report[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [plan, setPlan] = useState<AnalysisPlan | null>(null);
  const [privacy, setPrivacy] = useState<PaperPrivacy | null>(null);
  const [language, setLanguage] = useState("fa");
  const [approved, setApproved] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [source, setSource] = useState<{ before: string; quote: string; after: string; page: number } | null>(null);
  const pending = useRef<{ body: string; key: string } | null>(null);
  const active = report?.state === "queued" || report?.state === "running";
  const retry = report && ["failed", "partially_completed"].includes(report.state) ? report.id : null;
  const failure = useCallback((err: unknown) => {
    if (err instanceof ApiFailure && err.status === 401) expired();
    else setError((err as Error).message);
  }, [expired]);

  useEffect(() => {
    let alive = true;
    Promise.all([api<ReportPage>(`/papers/${paperId}/analyses`), api<PaperPrivacy>(`/papers/${paperId}`)])
      .then(([page, paper]) => { if (alive) { setHistory(page.items); setCursor(page.next_cursor); setPrivacy(paper); setSelected((previous) => previous || page.items[0]?.id || ""); } })
      .catch((err) => { if (alive) failure(err); });
    return () => { alive = false; };
  }, [paperId, refresh, failure]);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<Report>(`/analyses/${selected}`);
        if (!alive) return;
        setReport(value); setHistory((previous) => [value, ...previous.filter((item) => item.id !== value.id)]);
        if (["queued", "running"].includes(value.state)) timer = setTimeout(poll, 1500);
      } catch (err) { if (alive) { failure(err); timer = setTimeout(poll, 5000); } }
    }
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [selected, refresh, failure]);

  async function review() {
    setBusy(true); setError(""); setApproved(false); setPlan(null); pending.current = null;
    try { setPlan(await api<AnalysisPlan>(`/papers/${paperId}/analysis-plan?document_version_id=${versionId}&language=${language}`)); }
    catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function allowExternal(allow: boolean) {
    if (!privacy) return;
    setBusy(true); setError(""); setPlan(null); setApproved(false); pending.current = null;
    try {
      setPrivacy(await api<PaperPrivacy>(`/papers/${paperId}`, { method: "PATCH", headers: { "If-Match": `"${privacy.id}:${privacy.revision}"` }, body: JSON.stringify({ external_processing_allowed: allow }) }, session.csrf_token));
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function start() {
    if (!plan || !approved) return;
    const body = analysisBody(plan, versionId, language, plan.external_required && approved, retry, unknown);
    if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const queued = await api<{ id: string }>(`/papers/${paperId}/analyses`, { method: "POST", headers: { "Idempotency-Key": pending.current.key }, body }, session.csrf_token);
      setSelected(queued.id); setReport(null); setPlan(null); setApproved(false); setUnknown(false); setSource(null);
      pending.current = null; setRefresh((value) => value + 1);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function witness(reference: Witness) {
    if (!report) return;
    setBusy(true); setError("");
    try {
      const page = await api<{ id: string; text: string }>(`/document-versions/${report.document_version_id}/pages/${reference.page_number}`);
      const parts = evidenceParts(page.text, reference.start_offset, reference.end_offset);
      if (page.id !== reference.page_id || !parts || parts.quote !== reference.quote) throw new Error("Stored evidence does not match this source. The claim must be reviewed.");
      setSource({ ...parts, page: reference.page_number }); sourcePage(reference.page_number);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function older() {
    setBusy(true);
    try {
      const page = await api<ReportPage>(`/papers/${paperId}/analyses?cursor=${encodeURIComponent(cursor!)}`);
      setHistory((values) => [...values, ...page.items.filter((row) => !values.some((existing) => existing.id === row.id))]); setCursor(page.next_cursor);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  return <section className="analysis-panel" aria-label="Paper analysis">
    <div className="section-heading"><h2>Paper analysis</h2><button className="refresh-button" disabled={busy} onClick={() => { setError(""); setRefresh((value) => value + 1); }}>Reload reports</button></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    <p className="muted">Reports are AI-generated and require review. Exact quotes establish source locations, not the truth of an interpretation. Research suggestions do not establish novelty.</p>
    <label>Report language<select value={language} disabled={busy || active} onChange={(event) => { setLanguage(event.target.value); setPlan(null); setApproved(false); }}><option value="fa">فارسی</option><option value="en">English</option></select></label>
    {privacy && <label className="check-label"><input type="checkbox" checked={privacy.external_processing_allowed} disabled={busy} onChange={(event) => allowExternal(event.target.checked)} />Allow external AI processing for this paper</label>}
    <p className="muted">Local Mock does not send your document outside the application. Real providers receive the extracted text shown by the analysis plan.</p>
    <button className="refresh-button" disabled={busy || active || !ready} onClick={review}>{retry ? "Review full retry plan" : "Review new analysis plan"}</button>
    {!ready && <p className="muted">Select a ready extraction to create a new report. Older reports remain available.</p>}
    {plan && <div className="analysis-plan"><h3>Review destinations before starting</h3>
      <p>{plan.snapshot.included_chunks} / {plan.snapshot.total_chunks} text chunks · {plan.snapshot.coverage.replaceAll("_", " ")}</p>
      <ul>{plan.targets.map((target) => <li key={target.configuration_id}><strong>{target.model_name}</strong> · {target.execution_mode === "mock" ? "MOCK · local fixture" : target.adapter} · {target.base_url || "Local processing"} · {target.source}</li>)}</ul>
      <p className="muted">Seven report sections. Up to two attempts per section if an approved fallback is configured. External calls may incur charges; cost is unavailable. Ambiguous requests are not retried automatically.</p>
      {plan.external_required && !plan.external_processing_allowed && <p role="alert" className="error-message">Enable this paper&apos;s external processing permission, then review the plan again.</p>}
      <label className="check-label"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} />I approve these exact models and destinations, including configured fallbacks.</label>
      {retry && <p className="muted">This creates a full new report and reruns every section. The previous report is preserved.</p>}
      {retry && report?.outcome_unknown && <label className="check-label"><input type="checkbox" checked={unknown} onChange={(event) => setUnknown(event.target.checked)} />The previous request may have consumed quota. I checked the provider and approve a new run.</label>}
      <button className="primary-button" disabled={busy || active || !approved || (plan.external_required && !plan.external_processing_allowed) || !!(retry && report?.outcome_unknown && !unknown)} onClick={start}>{busy ? "Starting…" : "Start analysis"}</button>
    </div>}
    {history.length > 0 && <label>Analysis history<select value={selected} onChange={(event) => { setSelected(event.target.value); setReport(null); setSource(null); setPlan(null); setUnknown(false); }}><option value="" disabled>Select report</option>{history.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {item.language} · {item.state.replaceAll("_", " ")}</option>)}</select></label>}
    {cursor && <button className="refresh-button" disabled={busy} onClick={older}>Older reports</button>}
    {report && <>
      <p role="status">{report.state.replaceAll("_", " ")} · {report.progress}% {report.stage?.replaceAll("_", " ")}</p>
      {active && <progress max={100} value={report.progress} aria-label="Analysis progress" />}
      {isMockReport(report) && <p className="mock-banner">MOCK · This is a workflow fixture, not a scientific report.</p>}
      {report.error_code && <p className="error-message">{report.error_code.replaceAll("_", " ")}. Successful sections are preserved.</p>}
      <p className="muted">Coverage: {report.configuration.coverage.replaceAll("_", " ")}. Extraction warnings: {report.configuration.extraction_warnings.join(", ") || "none recorded"}.</p>
      <details><summary>Saved model, parser and analysis versions</summary><pre className="analysis-config">{JSON.stringify(report.configuration, null, 2)}</pre><p>Extraction version: {report.document_version_id}</p></details>
      <div dir={report.language === "fa" ? "rtl" : "ltr"}>
        {analysisSections.map((name) => {
          const part = report.sections.find((item) => item.kind === name);
          return <article className="report-section" key={name}><h3>{name.replaceAll("_", " ")}</h3>{!part ? <p>Not completed.</p> : part.error_code ? <p>{part.error_code.replaceAll("_", " ")}</p> : part.payload?.unavailable_reason ? <p>{part.payload.unavailable_reason}</p> : part.payload?.items.map((claim, index) => <div className="analysis-claim" key={index}><span className={`claim-kind claim-${claim.kind}`}>{claimLabels[claim.kind]}</span><p className="muted">{claim.topic.replaceAll("_", " ")}</p><p>{claim.text}</p>
            {claim.result && <dl>{Object.entries(claim.result).map(([field, value]) => <div key={field}><dt>{field}</dt><dd>{value ?? "Unavailable"}</dd></div>)}</dl>}
            {claim.resource && <p>{claim.resource.name} · {claim.resource.url || "No source URL"} · Document-extracted, unverified</p>}
            {claim.evidence.map((reference, number) => <details key={number}><summary>Evidence · page {reference.page_number}</summary><blockquote dir="auto">{reference.quote}</blockquote><button className="refresh-button" disabled={busy} onClick={() => witness(reference)}>Inspect source page {reference.page_number}</button></details>)}
          </div>)}</article>;
        })}
      </div>
      {source && <div className="analysis-source"><h3>Evidence in extracted text · page {source.page}</h3><pre className="extracted-text" dir="auto">{source.before}<mark>{source.quote}</mark>{source.after}</pre></div>}
      <details><summary>Analysis usage ({report.usage.length} requests)</summary><div className="usage-table"><table><thead><tr><th>Section / model</th><th>Status</th><th>Usage</th></tr></thead><tbody>{report.usage.map((attempt) => <tr key={attempt.id}><td>{attempt.section}<small>{attempt.model_name}</small></td><td>{attempt.state.replaceAll("_", " ")}</td><td>{attempt.total_tokens ?? "Unknown"} tokens<small>{attempt.execution_mode === "mock" ? "MOCK · synthetic usage · no external charge" : "Cost unavailable"}</small></td></tr>)}</tbody></table></div></details>
    </>}
  </section>;
}
