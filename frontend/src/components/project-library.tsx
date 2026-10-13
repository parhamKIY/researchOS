"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";

export type Project = { id: string; name: string; description: string; archived_at: string | null; revision: number };
type Page = { items: Project[]; next_cursor: string | null };
export function revisionHeaders(resource: { id: string; revision: number }) {
  return { "If-Match": `"${resource.id}:${resource.revision}"` };
}

export function ProjectLibrary({ session, expired, selected, select }: {
  session: Session; expired: () => void; selected: string; select: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [archived, setArchived] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Project | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api<Page>(`/projects?archived=${archived}&limit=20`).then((page) => {
      if (alive) { setProjects(page.items); setCursor(page.next_cursor); setError(""); }
    }).catch((err) => {
      if (alive) { if (err instanceof ApiFailure && err.status === 401) expired(); else setError(err.message); }
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [archived, refresh, expired]);

  async function action(work: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await work(); setEditing(null); setCreating(false); setDeleting(null); setRefresh((n) => n + 1); }
    catch (err) {
      if (err instanceof ApiFailure && err.status === 401) expired();
      else setError((err as Error).message);
    } finally { setBusy(false); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = JSON.stringify({ name: form.get("name"), description: form.get("description") });
    await action(() => api(editing ? `/projects/${editing.id}` : "/projects", {
      method: editing ? "PATCH" : "POST", body,
      headers: editing ? revisionHeaders(editing) : {},
    }, session.csrf_token));
  }

  async function more() {
    if (!cursor) return;
    setBusy(true);
    try {
      const page = await api<Page>(`/projects?archived=${archived}&limit=20&cursor=${encodeURIComponent(cursor)}`);
      setProjects((items) => [...items, ...page.items]); setCursor(page.next_cursor);
    } catch (err) { if (err instanceof ApiFailure && err.status === 401) expired(); else setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="library-panel" aria-label="Research projects">
    <div className="section-heading"><div><p className="eyebrow">Organize your work</p><h2>Research projects</h2></div>
      <button className="primary-button" disabled={busy} onClick={() => { setCreating(true); setEditing(null); }}>New project</button></div>
    <div className="toolbar"><button className={!archived ? "tab active" : "tab"} onClick={() => { setArchived(false); setLoading(true); }}>Active</button>
      <button className={archived ? "tab active" : "tab"} onClick={() => { setArchived(true); setLoading(true); }}>Archived</button>
      <button className="refresh-button" onClick={() => setRefresh((n) => n + 1)}>Refresh</button></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    {(creating || editing) && <form className="inline-form" key={editing ? `${editing.id}:${editing.revision}` : "new"} onSubmit={save}>
      <label>Project name<input name="name" required maxLength={200} defaultValue={editing?.name ?? ""} /></label>
      <label>Description<textarea name="description" maxLength={5000} rows={3} defaultValue={editing?.description ?? ""} /></label>
      <div className="toolbar"><button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save project"}</button>
        <button className="refresh-button" type="button" onClick={() => { setCreating(false); setEditing(null); }}>Cancel</button></div>
    </form>}
    {loading ? <p role="status" className="muted">Loading projects…</p> : projects.length === 0 ? <p className="empty-state">{archived ? "No archived projects." : "Create your first project to organize related papers."}</p> : <div className="project-grid">
      {projects.map((project) => <article className={selected === project.id ? "project-card selected" : "project-card"} key={project.id}>
        <button className="project-title" onClick={() => select(selected === project.id ? "" : project.id)} aria-pressed={selected === project.id}>{project.name}</button>
        <p>{project.description || "No description yet."}</p>
        <div className="card-actions">
          <button disabled={busy} onClick={() => { setEditing(project); setCreating(false); }}>Edit</button>
          <button disabled={busy} onClick={() => action(() => api(`/projects/${project.id}`, { method: "PATCH", headers: revisionHeaders(project), body: JSON.stringify({ archived: !project.archived_at }) }, session.csrf_token))}>{project.archived_at ? "Restore" : "Archive"}</button>
          <button disabled={busy} onClick={() => setDeleting(project.id)}>Delete</button>
        </div>
        {deleting === project.id && <div className="delete-confirm"><p>Delete this project? Its papers remain in your library.</p><button className="danger-button" disabled={busy} onClick={() => action(async () => {
          await api(`/projects/${project.id}`, { method: "DELETE", headers: revisionHeaders(project) }, session.csrf_token);
          if (selected === project.id) select("");
        })}>Confirm delete</button><button disabled={busy} onClick={() => setDeleting(null)}>Cancel</button></div>}
      </article>)}
    </div>}
    {cursor && <button className="refresh-button" disabled={busy} onClick={more}>Load more projects</button>}
  </section>;
}
