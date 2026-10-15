"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";
import { revisionHeaders } from "@/components/project-library";

type Provider = { id: string; adapter: "gemini" | "mock"; display_name: string; credential_configured: boolean; credential_display: string | null; enabled: boolean; revision: number };
type Model = { id: string; provider_id: string; model_name: string; capabilities: string[]; capability_source: string; parameters: { temperature: number | null; max_output_tokens: number | null }; enabled: boolean; revision: number };
type Rule = { task: string; primary_model_id: string; fallback_model_id: string | null; allowed_provider_ids: string[] };
type Routing = { rules: Rule[]; revision: number; updated_at: string };
type Page<T> = { items: T[]; next_cursor: string | null };
type Usage = { id: string; provider_name: string; model_name: string; execution_mode: string; state: string; attempt: number; total_tokens: number | null; latency_ms: number | null; cost_amount: number | null; currency: string | null; created_at: string };
const tasks = [{ value: "paper_summary", label: "Paper summary", capability: "text" }, { value: "methodology", label: "Methodology", capability: "text" }, { value: "research_gaps", label: "Research gaps", capability: "text" }, { value: "paper_chat", label: "Paper chat", capability: "text" }, { value: "figure_analysis", label: "Figure analysis", capability: "vision" }, { value: "embeddings", label: "Embeddings", capability: "embeddings" }];

export function ProviderSettings({ session, expired }: { session: Session; expired: () => void }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [modelCursors, setModelCursors] = useState<Record<string, string | null>>({});
  const [routing, setRouting] = useState<Routing | null>(null);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [usageCursor, setUsageCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [adapter, setAdapter] = useState("gemini");
  const [refresh, setRefresh] = useState(0);
  const [removing, setRemoving] = useState("");
  const [editing, setEditing] = useState("");
  const [routeEdits, setRouteEdits] = useState<Record<string, { primary: string; fallback: string }>>({});

  const failure = useCallback((err: unknown) => {
    if (err instanceof ApiFailure && err.status === 401) expired();
    else setError((err as Error).message);
  }, [expired]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const [page, routes, history] = await Promise.all([api<Page<Provider>>("/providers"), api<Routing>("/settings/model-routing"), api<Page<Usage>>("/analytics/usage")]);
        const configured = await Promise.all(page.items.map((provider) => api<Page<Model>>(`/providers/${provider.id}/models`)));
        if (alive) { setProviders(page.items); setCursor(page.next_cursor); setModels(configured.flatMap((item) => item.items)); setModelCursors(Object.fromEntries(page.items.map((provider, index) => [provider.id, configured[index].next_cursor]))); setRouting(routes); setUsage(history.items); setUsageCursor(history.next_cursor); }
      } catch (err) { if (alive) failure(err); }
    }
    void load();
    return () => { alive = false; };
  }, [refresh, failure]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setNotice(success); setRefresh((value) => value + 1); return true; }
    catch (err) { failure(err); return false; }
    finally { setBusy(false); }
  }

  async function addProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget, form = new FormData(element);
    const payload: Record<string, unknown> = { adapter, display_name: form.get("display_name") };
    if (adapter === "gemini") payload.api_key = form.get("api_key");
    if (await mutate(() => api("/providers", { method: "POST", body: JSON.stringify(payload) }, session.csrf_token), "Provider saved. Its key is kept encrypted on the server.")) element.reset();
  }

  async function updateProvider(event: FormEvent<HTMLFormElement>, provider: Provider) {
    event.preventDefault();
    const element = event.currentTarget, form = new FormData(element);
    const payload: Record<string, unknown> = { display_name: form.get("display_name"), enabled: form.get("enabled") === "on" };
    const key = String(form.get("api_key") || "");
    if (key) payload.api_key = key;
    if (await mutate(() => api(`/providers/${provider.id}`, { method: "PATCH", headers: revisionHeaders(provider), body: JSON.stringify(payload) }, session.csrf_token), "Provider settings updated.")) element.reset();
  }

  function modelPayload(form: FormData) {
    const parameters: Record<string, number> = {};
    if (String(form.get("temperature") || "").trim()) parameters.temperature = Number(form.get("temperature"));
    if (String(form.get("max_output_tokens") || "").trim()) parameters.max_output_tokens = Number(form.get("max_output_tokens"));
    return { model_name: form.get("model_name"), capabilities: form.getAll("capabilities"), parameters };
  }

  async function addModel(event: FormEvent<HTMLFormElement>, provider: Provider) {
    event.preventDefault(); const element = event.currentTarget;
    if (await mutate(() => api(`/providers/${provider.id}/models`, { method: "POST", body: JSON.stringify(modelPayload(new FormData(element))) }, session.csrf_token), "Model saved. Declared capabilities still require provider verification.")) element.reset();
  }

  async function updateModel(event: FormEvent<HTMLFormElement>, model: Model) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    if (await mutate(() => api(`/models/${model.id}`, { method: "PATCH", headers: revisionHeaders(model), body: JSON.stringify({ ...modelPayload(form), enabled: form.get("enabled") === "on" }) }, session.csrf_token), "Model configuration updated without restarting the backend.")) setEditing("");
  }

  async function test(provider: Provider, model: Model) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<{ status: string; code: string; execution_mode: string; outcome_unknown: boolean }>(`/providers/${provider.id}/test`, { method: "POST", body: JSON.stringify({ model_configuration_id: model.id }) }, session.csrf_token);
      const message = `${result.execution_mode.toUpperCase()}: ${result.code.replaceAll("_", " ")}.${result.outcome_unknown ? " The provider outcome and cost are unknown. A new test may incur another charge." : ""}`;
      if (result.status === "ok") setNotice(message); else setError(message);
      setRefresh((value) => value + 1);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function saveRoutes() {
    if (!routing) return;
    const rules: Rule[] = [];
    for (const task of tasks) {
      const original = routing.rules.find((rule) => rule.task === task.value);
      const values = routeEdits[task.value] ?? { primary: original?.primary_model_id || "", fallback: original?.fallback_model_id || "" };
      if (!values.primary) continue;
      const selected = [values.primary, values.fallback].filter(Boolean).map((id) => models.find((model) => model.id === id));
      const allowed = selected.every(Boolean) ? [...new Set(selected.map((model) => model!.provider_id))] : original?.allowed_provider_ids || [];
      rules.push({ task: task.value, primary_model_id: values.primary, fallback_model_id: values.fallback || null, allowed_provider_ids: allowed });
    }
    if (await mutate(() => api("/settings/model-routing", { method: "PUT", headers: { "If-Match": `"${session.user.id}:${routing.revision}"` }, body: JSON.stringify({ rules }) }, session.csrf_token), "Task routes saved. Only these explicitly selected providers are allowed.")) setRouteEdits({});
  }

  async function more(kind: "providers" | "models" | "usage", providerId?: string) {
    setBusy(true);
    try {
      if (kind === "providers") {
        const page = await api<Page<Provider>>(`/providers?cursor=${encodeURIComponent(cursor!)}`);
        const configured = await Promise.all(page.items.map((provider) => api<Page<Model>>(`/providers/${provider.id}/models`)));
        setProviders((values) => [...values, ...page.items]); setCursor(page.next_cursor); setModels((values) => [...values, ...configured.flatMap((item) => item.items)]); setModelCursors((values) => ({ ...values, ...Object.fromEntries(page.items.map((provider, index) => [provider.id, configured[index].next_cursor])) }));
      } else if (kind === "models") {
        const page = await api<Page<Model>>(`/providers/${providerId}/models?cursor=${encodeURIComponent(modelCursors[providerId!]!)}`);
        setModels((values) => [...values, ...page.items]); setModelCursors((values) => ({ ...values, [providerId!]: page.next_cursor }));
      } else {
        const page = await api<Page<Usage>>(`/analytics/usage?cursor=${encodeURIComponent(usageCursor!)}`);
        setUsage((values) => [...values, ...page.items]); setUsageCursor(page.next_cursor);
      }
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  function parameters(model?: Model) { return <div className="settings-fields"><label>Temperature (optional)<input name="temperature" type="number" min="0" max="2" step="0.1" defaultValue={model?.parameters.temperature ?? ""} /></label><label>Maximum output tokens (optional)<input name="max_output_tokens" type="number" min="16" max="8192" step="1" defaultValue={model?.parameters.max_output_tokens ?? ""} /></label></div>; }
  function capabilities(model?: Model) { return <fieldset><legend>Declared capabilities · unverified</legend>{["text", "vision", "embeddings"].map((value) => <label className="check-label" key={value}><input type="checkbox" name="capabilities" value={value} defaultChecked={model ? model.capabilities.includes(value) : value === "text"} />{value}</label>)}</fieldset>; }
  function label(model: Model) { return `${providers.find((provider) => provider.id === model.provider_id)?.display_name || "Unavailable provider"} / ${model.model_name}${model.enabled ? "" : " (disabled)"}`; }

  return <section className="library-panel provider-settings" aria-label="AI provider settings" id="ai-settings">
    <div className="section-heading"><h2>AI providers & models</h2><button className="refresh-button" disabled={busy} onClick={() => { setError(""); setRefresh((value) => value + 1); }}>Reload settings</button></div>
    <p className="muted">Bring your own Gemini key. Saved keys are encrypted and never returned. Mock runs are explicitly labeled. Open a paper to review and start an evidence-linked analysis.</p>
    {error && <p role="alert" className="error-message">{error}</p>}{notice && <p role="status" className="success-message">{notice}</p>}
    <form onSubmit={addProvider} className="provider-form"><h3>Add provider</h3><div className="settings-fields"><label>Adapter<select aria-label="Provider adapter" value={adapter} onChange={(event) => setAdapter(event.target.value)}><option value="gemini">Google Gemini · external</option><option value="mock">Mock · local test fixture</option></select></label><label>Provider name<input name="display_name" required maxLength={100} /></label></div>
      {adapter === "gemini" && <label>Gemini API key<input name="api_key" type="password" autoComplete="off" required minLength={10} maxLength={512} spellCheck={false} /></label>}<button className="primary-button" disabled={busy}>Save provider</button></form>
    {providers.length === 0 && <p className="empty-state">No providers configured.</p>}
    {providers.map((provider) => <article key={provider.id} className="provider-card" aria-label={provider.display_name}>
      <div className="section-heading"><h3>{provider.display_name}</h3><span className="paper-state">{provider.adapter.toUpperCase()} · {provider.enabled ? "enabled" : "disabled"} · {provider.credential_display || "No stored key"}</span></div>
      <details><summary>Provider settings</summary><form key={provider.revision} onSubmit={(event) => updateProvider(event, provider)}><label>Display name<input name="display_name" defaultValue={provider.display_name} maxLength={100} required /></label><label className="check-label"><input type="checkbox" name="enabled" defaultChecked={provider.enabled} />Enabled</label>{provider.adapter === "gemini" && <label>Replacement key (optional)<input name="api_key" type="password" autoComplete="off" minLength={10} maxLength={512} spellCheck={false} /></label>}<button className="refresh-button" disabled={busy}>Update provider</button></form>
        <div className="toolbar">{provider.adapter === "gemini" && provider.credential_configured && <button className="refresh-button" disabled={busy} onClick={() => mutate(() => api(`/providers/${provider.id}`, { method: "PATCH", headers: revisionHeaders(provider), body: JSON.stringify({ clear_credential: true }) }, session.csrf_token), "Stored credential removed.")}>Remove stored key</button>}<button className="refresh-button" disabled={busy} onClick={() => setRemoving(provider.id)}>Delete provider</button></div>
        {removing === provider.id && <div className="delete-confirm"><p>Disable this provider and remove its saved key? Usage history is retained.</p><button disabled={busy} className="danger-button" onClick={async () => { if (await mutate(() => api(`/providers/${provider.id}`, { method: "DELETE", headers: revisionHeaders(provider) }, session.csrf_token), "Provider disabled and key removed.")) setRemoving(""); }}>Confirm provider deletion</button><button onClick={() => setRemoving("")}>Cancel</button></div>}</details>
      <p className="muted">Testing a text model sends only a fixed connection message to {provider.adapter === "gemini" ? "Google Gemini and may consume quota or incur charges (up to 256 output tokens per attempt)." : "the local mock adapter. It does not contact Google."} No paper is sent. Vision and embedding declarations are not verified by this test.</p>
      {models.filter((model) => model.provider_id === provider.id).map((model) => <div className="model-row" key={model.id}><strong>{model.model_name}</strong><small>{model.capabilities.join(", ")} · manual, unverified · {model.enabled ? "enabled" : "disabled"}</small><div className="toolbar"><button className="refresh-button" disabled={busy || !provider.enabled || !model.enabled || !model.capabilities.includes("text") || provider.adapter === "gemini" && !provider.credential_configured} onClick={() => test(provider, model)}>Test {provider.adapter === "mock" ? "mock" : "Gemini"} connection</button><button className="refresh-button" disabled={busy} onClick={() => setEditing(editing === model.id ? "" : model.id)}>Edit model</button></div>
        {editing === model.id && <form onSubmit={(event) => updateModel(event, model)}><label>Model ID<input name="model_name" required maxLength={200} defaultValue={model.model_name} /></label>{capabilities(model)}{parameters(model)}<label className="check-label"><input name="enabled" type="checkbox" defaultChecked={model.enabled} />Enabled</label><button className="refresh-button" disabled={busy}>Update model</button><button type="button" className="refresh-button" disabled={busy} onClick={() => mutate(() => api(`/models/${model.id}`, { method: "DELETE", headers: revisionHeaders(model) }, session.csrf_token), "Model disabled; existing usage retained.")}>Disable model</button></form>}</div>)}
      {modelCursors[provider.id] && <button className="refresh-button" disabled={busy} onClick={() => more("models", provider.id)}>More models</button>}
      <details><summary>Add model</summary><form onSubmit={(event) => addModel(event, provider)}><label>Model ID<input name="model_name" required maxLength={200} placeholder={provider.adapter === "mock" ? "fixture-model" : "Exact model ID from Google AI Studio"} /></label>{capabilities()}{parameters()}<button className="refresh-button" disabled={busy}>Save model</button></form></details>
    </article>)}
    {cursor && <button className="refresh-button" disabled={busy} onClick={() => more("providers")}>More providers</button>}
    <details><summary>Default models by task</summary><p className="muted">Select a primary model and an optional fallback. Each analysis separately requires approval of its exact destinations and the paper&apos;s external-processing permission. Routes use declared capabilities and do not verify model availability. Figure, chat and embedding execution belong to later milestones.</p>
      {tasks.map((task) => { const original = routing?.rules.find((rule) => rule.task === task.value); const values = routeEdits[task.value] ?? { primary: original?.primary_model_id || "", fallback: original?.fallback_model_id || "" }; const candidates = models.filter((model) => model.enabled && model.capabilities.includes(task.capability) && providers.some((provider) => provider.id === model.provider_id && provider.enabled && (provider.adapter === "mock" || provider.credential_configured))); return <div className="settings-fields" key={task.value}><label>{task.label}<select aria-label={`${task.label} primary model`} value={values.primary} onChange={(event) => setRouteEdits((edits) => ({ ...edits, [task.value]: { primary: event.target.value, fallback: "" } }))}><option value="">Not configured</option>{values.primary && !candidates.some((model) => model.id === values.primary) && <option value={values.primary}>Configured model unavailable</option>}{candidates.map((model) => <option key={model.id} value={model.id}>{label(model)}</option>)}</select></label><label>Optional fallback<select aria-label={`${task.label} fallback model`} value={values.fallback} disabled={!values.primary} onChange={(event) => setRouteEdits((edits) => ({ ...edits, [task.value]: { ...values, fallback: event.target.value } }))}><option value="">No fallback</option>{values.fallback && !candidates.some((model) => model.id === values.fallback) && <option value={values.fallback}>Configured fallback unavailable</option>}{candidates.filter((model) => model.id !== values.primary).map((model) => <option key={model.id} value={model.id}>{label(model)}</option>)}</select></label></div>; })}
      <button className="refresh-button" disabled={busy || !routing} onClick={saveRoutes}>Save task routes</button></details>
    <details><summary>Connection usage history</summary><p className="muted">Each request attempt is recorded. Unknown token counts and costs stay unknown; mock counts are synthetic and have no provider charge.</p>{usage.length === 0 ? <p>No connection requests recorded.</p> : <div className="usage-table"><table><thead><tr><th>Provider / model</th><th>Mode / state</th><th>Tokens</th><th>Latency</th><th>Cost</th></tr></thead><tbody>{usage.map((record) => <tr key={record.id}><td>{record.provider_name}<br />{record.model_name}<small>{new Date(record.created_at).toLocaleString()} · attempt {record.attempt}</small></td><td>{record.execution_mode} · {record.state.replaceAll("_", " ")}</td><td>{record.total_tokens ?? "Unknown"}</td><td>{record.latency_ms === null ? "Unknown" : `${record.latency_ms} ms`}</td><td>{record.cost_amount === null ? "Unknown" : `${record.cost_amount} ${record.currency || ""}`}</td></tr>)}</tbody></table></div>}{usageCursor && <button className="refresh-button" disabled={busy} onClick={() => more("usage")}>Older usage</button>}</details>
  </section>;
}
