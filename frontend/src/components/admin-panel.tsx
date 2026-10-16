"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";
import { connectionMessage, geminiBase, type ApplyResult, type ModelCatalog, type SystemAdapter, type SystemSettings } from "@/lib/system-llm";
import { ProviderModelSelect } from "@/components/provider-model-select";

type AdminUser = { id: string; email: string; is_active: boolean; is_admin: boolean; etag: string };
type Users = { items: AdminUser[]; next_cursor: string | null };
type Overview = { users: number; active_users: number; projects: number; papers: number };

export function AdminPanel({ session, expired }: { session: Session; expired: () => void }) {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [users, setUsers] = useState<Users | null>(null);
  const [adapter, setAdapter] = useState<SystemAdapter>("gemini");
  const [baseUrl, setBaseUrl] = useState(geminiBase);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [model, setModel] = useState("");
  const [listing, setListing] = useState(false);
  const keyInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [allowed, setAllowed] = useState(true);

  const failure = useCallback((err: unknown) => {
    if (err instanceof ApiFailure && err.status === 401) expired();
    else {
      if (err instanceof ApiFailure && err.status === 403) setAllowed(false);
      setError((err as Error).message);
    }
  }, [expired]);

  const load = useCallback(async () => {
    const [config, stats, accounts] = await Promise.all([
      api<SystemSettings>("/admin/llm"), api<Overview>("/admin/overview"), api<Users>("/admin/users"),
    ]);
    return { config, stats, accounts };
  }, []);

  function applyConfig(config: SystemSettings) {
    setSettings(config);
    setAdapter(config.active?.adapter ?? "gemini");
    setBaseUrl(config.active?.base_url ?? geminiBase);
    setCatalog(null); setModel("");
    if (keyInput.current) keyInput.current.value = "";
  }

  useEffect(() => {
    let alive = true;
    load().then(({ config, stats, accounts }) => {
      if (alive) { applyConfig(config); setOverview(stats); setUsers(accounts); }
    }).catch((err) => { if (alive) failure(err); });
    return () => { alive = false; };
  }, [load, failure]);

  async function reload() {
    setBusy(true); setError(""); setNotice("");
    try {
      const { config, stats, accounts } = await load();
      applyConfig(config); setOverview(stats); setUsers(accounts);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || (adapter !== "mock" && !catalog?.items.some((item) => item.id === model))) return;
    const element = event.currentTarget, form = new FormData(element);
    const parameters: Record<string, number> = {};
    if (String(form.get("temperature") || "").trim()) parameters.temperature = Number(form.get("temperature"));
    if (String(form.get("max_output_tokens") || "").trim()) parameters.max_output_tokens = Number(form.get("max_output_tokens"));
    const payload: Record<string, unknown> = { adapter, model_name: adapter === "mock" ? "fixture-model" : model, parameters };
    if (adapter !== "mock") {
      payload.base_url = baseUrl;
      const key = String(form.get("api_key") || "").trim();
      if (key) payload.api_key = key;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<ApplyResult>("/admin/llm/verify-and-apply", {
        method: "POST", headers: { "If-Match": settings.etag }, body: JSON.stringify(payload),
      }, session.csrf_token);
      setSettings(result.settings);
      if (result.applied) {
        applyConfig(result.settings);
        setNotice(result.check.execution_mode === "mock" ? "Local mock verified and activated. No external provider was contacted." : "Connection verified. The system default is now active.");
      } else setError(`${connectionMessage(result.check)} The active configuration was kept.`);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function fetchModels(element: HTMLFormElement | null) {
    if (!element) return;
    const form = new FormData(element);
    const key = String(form.get("api_key") || "").trim();
    const payload = { adapter, base_url: baseUrl, ...(key ? { api_key: key } : {}) };
    setListing(true); setError(""); setNotice(""); setCatalog(null); setModel("");
    try {
      const result = await api<ModelCatalog>("/admin/llm/models", {
        method: "POST", body: JSON.stringify(payload),
      }, session.csrf_token);
      setCatalog(result);
      // Preserve an active choice only when the provider actually lists it.
      const previous = settings?.active?.model_name;
      setModel(result.items.some((item) => item.id === previous) ? previous! : "");
      if (!result.items.length) setError("The provider returned no selectable text-generation models for these credentials.");
    } catch (err) {
      // A provider's HTTP 403 is returned as 502; only local access denial hides this panel.
      failure(err);
    } finally { setListing(false); }
  }

  function invalidateCatalog() { setCatalog(null); setModel(""); setError(""); setNotice(""); }

  async function changeStatus(user: AdminUser) {
    setBusy(true); setError(""); setNotice("");
    try {
      const changed = await api<AdminUser>(`/admin/users/${user.id}`, {
        method: "PATCH", headers: { "If-Match": user.etag }, body: JSON.stringify({ is_active: !user.is_active }),
      }, session.csrf_token);
      setUsers((page) => page && ({ ...page, items: page.items.map((item) => item.id === changed.id ? changed : item) }));
      setOverview(await api<Overview>("/admin/overview"));
      setNotice(changed.is_active ? "Account enabled. The user can sign in again." : "Account disabled. Its active sessions were revoked.");
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function moreUsers() {
    if (!users?.next_cursor) return;
    setBusy(true); setError("");
    try {
      const page = await api<Users>(`/admin/users?cursor=${encodeURIComponent(users.next_cursor)}`);
      setUsers((previous) => ({ ...page, items: [...(previous?.items ?? []), ...page.items] }));
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  if (!allowed) return <p role="alert" className="error-message">Administrator access is required. <a href="/">Return to your workspace.</a></p>;
  return <div className="admin-panel">
    <div className="section-heading"><p className="intro">Manage accounts and the default text model for the system.</p><button className="refresh-button" onClick={reload} disabled={busy || listing}>Reload settings</button></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    {notice && <p role="status" className="success-message">{notice}</p>}
    {overview && <dl className="admin-stats"><div><dt>Accounts</dt><dd>{overview.users}</dd></div><div><dt>Active accounts</dt><dd>{overview.active_users}</dd></div><div><dt>Projects</dt><dd>{overview.projects}</dd></div><div><dt>Papers</dt><dd>{overview.papers}</dd></div></dl>}
    <section className="library-panel provider-settings">
      <h2>System LLM provider</h2>
      {!settings ? <p role="status">Loading settings…</p> : <>
        <div className="system-model-card"><p className="eyebrow">Currently active</p>
          {settings.active ? <><strong>{settings.active.model_name}</strong><p>{settings.active.adapter === "mock" ? "MOCK · local fixture" : `${settings.active.adapter} · connection verified`}</p><p className="muted">{settings.active.base_url ?? "No external endpoint"} · {settings.active.credential_configured ? "Key stored securely" : "No external key"}</p></> : <p>No system provider has been activated.</p>}
        </div>
        <form key={settings.active?.id ?? "empty"} className="provider-form" onSubmit={apply}>
          <fieldset disabled={busy || listing} className="admin-fields"><legend>New configuration</legend>
            <div className="settings-fields"><label>API protocol<select value={adapter} onChange={(event) => {
              const next = event.target.value as SystemAdapter;
              setAdapter(next); setBaseUrl(next === "gemini" ? geminiBase : ""); invalidateCatalog();
              if (keyInput.current) keyInput.current.value = "";
            }}><option value="gemini">Google Gemini</option><option value="openai_compatible">OpenAI-compatible · custom endpoint</option><option value="mock">Mock · local fixture</option></select></label>
              <ProviderModelSelect adapter={adapter} catalog={catalog} value={model} onChange={setModel} /></div>
            {adapter !== "mock" && <>
              <label>Provider API base URL<input name="base_url" type="url" required maxLength={500} value={baseUrl} readOnly={adapter === "gemini"} onChange={(event) => { setBaseUrl(event.target.value); invalidateCatalog(); if (keyInput.current) keyInput.current.value = ""; }} placeholder="https://api.example.com/v1" spellCheck={false} /></label>
              <p className="muted">For a compatible provider, enter its public HTTPS API base URL, including its version path. The connection test calls chat/completions. Gemini uses its official endpoint.</p>
              <label>API key<input ref={keyInput} name="api_key" type="password" autoComplete="off" maxLength={4096} spellCheck={false} onChange={invalidateCatalog} /></label>
              <p className="muted">Enter a new key when changing provider or URL. Leave blank to reuse the stored key only for the same protocol and endpoint. Keys are never shown.</p>
              <button type="button" className="refresh-button" onClick={(event) => fetchModels(event.currentTarget.form)} disabled={busy || listing || !baseUrl}>{listing ? "Loading models…" : "Load available models"}</button>
              <p className="muted">{catalog ? `${catalog.items.length} models listed. ` : ""}Listing sends no paper and does not activate settings. {adapter === "gemini" ? "Only models advertising generateContent are shown." : "This provider may also list models that do not support chat/completions."} A successful connection test is still required; listing does not guarantee generation permissions, quota or regional availability.</p>
            </>}
            <div className="settings-fields"><label>Temperature (optional)<input name="temperature" type="number" min={0} max={2} step="0.1" defaultValue={settings.active?.parameters.temperature ?? ""} /></label><label>Output token limit (optional)<input name="max_output_tokens" type="number" min={16} max={8192} step={1} defaultValue={settings.active?.parameters.max_output_tokens ?? ""} /></label></div>
            <p className="muted">{adapter === "mock" ? "This tests only a local fixture. It does not verify a real provider." : "The test sends a fixed connection message and may consume quota or incur charges. Test output is capped at 256 tokens; this is not a guaranteed cost limit."} No paper is sent. The active configuration changes only after a successful test.</p>
            <button className="primary-button" disabled={busy || listing || (adapter !== "mock" && !model)}>{busy ? "Testing connection…" : "Test connection and apply"}</button>
          </fieldset>
        </form>
        <p className="muted">The default applies to text tasks with no personal route. Paper owners must separately allow external processing and approve their analysis plan.</p>
        <details><summary>Recent connection checks</summary><div className="usage-table"><table><caption className="sr-only">System provider connection checks</caption><thead><tr><th>Model / protocol</th><th>Status</th><th>Checked</th><th>Usage</th></tr></thead><tbody>{settings.checks.map((check) => <tr key={check.id}><td>{check.model_name}<small>{check.execution_mode === "mock" ? "MOCK · synthetic usage" : check.adapter}</small></td><td>{check.state}{check.error_code && <small>{connectionMessage(check)}</small>}</td><td>{check.checked_at ? new Date(check.checked_at).toLocaleString() : "Pending"}</td><td>{check.total_tokens === null ? "Unknown tokens" : `${check.total_tokens} tokens`}<small>{check.latency_ms === null ? "" : `${check.latency_ms} ms · `}{check.execution_mode === "mock" ? "No external charge" : "Cost unavailable"}</small></td></tr>)}</tbody></table>{settings.checks.length === 0 && <p>No checks recorded.</p>}</div></details>
      </>}
    </section>
    <section className="library-panel"><h2>User access</h2><p className="muted">Disabling an account revokes its sessions. Administrator roles and administrator accounts are managed through local setup.</p><div className="usage-table"><table><caption className="sr-only">Account access controls</caption><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Access</th></tr></thead><tbody>{users?.items.map((user) => <tr key={user.id}><td>{user.email}</td><td>{user.is_admin ? "Administrator" : "Researcher"}</td><td>{user.is_active ? "Active" : "Disabled"}</td><td>{user.is_admin || user.id === session.user.id ? "Protected" : <button className="refresh-button" disabled={busy} onClick={() => changeStatus(user)}>{user.is_active ? "Disable account" : "Enable account"}</button>}</td></tr>)}</tbody></table></div>{users?.next_cursor && <button className="refresh-button" disabled={busy} onClick={moreUsers}>More accounts</button>}</section>
  </div>;
}
