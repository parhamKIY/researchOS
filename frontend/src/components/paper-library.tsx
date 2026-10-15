"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";
import { revisionHeaders } from "@/components/project-library";
import { PdfViewer } from "@/components/pdf-viewer";
import { DocumentExtraction } from "@/components/document-extraction";

type Paper = { id: string; title: string | null; original_name: string; byte_size: number; project_ids: string[]; revision: number; processing_state: string; latest_ingestion_job_id: string | null };
type Page = { items: Paper[]; next_cursor: string | null };

export function PaperLibrary({ session, expired, project }: { session: Session; expired: () => void; project: string }) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Paper | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [requestedPage, setRequestedPage] = useState({ number: 1, request: 0 });
  const selectedId = selected?.id;
  const changed = useCallback(() => {
    if (!selectedId) return;
    api<Paper>(`/papers/${selectedId}`).then((value) => {
      setSelected((current) => current?.id === value.id ? value : current);
      setRefresh((value) => value + 1);
    }).catch((err) => { if (err instanceof ApiFailure && err.status === 401) expired(); else setError(err.message); });
  }, [selectedId, expired]);
  const sourcePage = useCallback((number: number) => { setRequestedPage((value) => ({ number, request: value.request + 1 })); }, []);
  const pendingUpload = useRef<{ file: File; project: string; key: string } | null>(null);
  const filter = `/papers?limit=20&q=${encodeURIComponent(query)}${project ? `&project_id=${project}` : ""}`;

  useEffect(() => {
    let alive = true;
    api<Page>(filter).then((page) => {
      if (alive) { setPapers(page.items); setCursor(page.next_cursor); setError(""); }
    }).catch((err) => {
      if (alive) { if (err instanceof ApiFailure && err.status === 401) expired(); else setError(err.message); }
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [filter, refresh, expired]);

  function failure(err: unknown) {
    if (err instanceof ApiFailure && err.status === 401) expired();
    else setError((err as Error).message);
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const file = new FormData(element).get("file") as File;
    if (!file?.size) return;
    // Keep the key for a retry after a timeout or lost response.
    const previous = pendingUpload.current;
    if (!previous || previous.file.name !== file.name || previous.file.size !== file.size || previous.file.lastModified !== file.lastModified || previous.project !== project) {
      pendingUpload.current = { file, project, key: crypto.randomUUID() };
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<{ paper: Paper; duplicate: boolean }>(`/papers/upload?filename=${encodeURIComponent(file.name)}${project ? `&project_id=${project}` : ""}`, {
        method: "POST", body: file, headers: { "Content-Type": "application/pdf", "Idempotency-Key": pendingUpload.current!.key }, signal: AbortSignal.timeout(120000),
      }, session.csrf_token);
      setNotice(result.duplicate ? "This PDF is already in your library. Its existing copy was reused." : "PDF saved to your private library.");
      setSelected(result.paper); setDeleting(false); setRefresh((n) => n + 1);
      setRequestedPage({ number: 1, request: 0 });
      pendingUpload.current = null; element.reset();
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function open(paper: Paper) {
    setError("");
    try { setSelected(await api<Paper>(`/papers/${paper.id}`)); setDeleting(false); setRequestedPage({ number: 1, request: 0 }); }
    catch (err) { failure(err); }
  }

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const title = String(new FormData(event.currentTarget).get("title") ?? "").trim();
    setBusy(true); setError("");
    try {
      setSelected(await api<Paper>(`/papers/${selected.id}`, { method: "PATCH", headers: revisionHeaders(selected), body: JSON.stringify({ title: title || null }) }, session.csrf_token));
      setRefresh((n) => n + 1);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await api(`/papers/${selected.id}`, { method: "DELETE", headers: revisionHeaders(selected) }, session.csrf_token);
      setSelected(null); setDeleting(false); setRefresh((n) => n + 1); setNotice("Paper deleted from your library.");
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function more() {
    if (!cursor) return;
    setBusy(true);
    try {
      const page = await api<Page>(`${filter}&cursor=${encodeURIComponent(cursor)}`);
      setPapers((items) => [...items, ...page.items]); setCursor(page.next_cursor);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  return <section className="library-panel" aria-label="Paper library">
    <div className="section-heading"><div><p className="eyebrow">Keep your sources close</p><h2>Paper library</h2></div>
      <button className="refresh-button" disabled={busy} onClick={() => setRefresh((n) => n + 1)}>Refresh papers</button></div>
    <p className="muted">{project ? "Showing papers in the selected project. New uploads will be added to it." : "All papers in your private library. Select a project above to filter or organize uploads."}</p>
    <form className="upload-form" onSubmit={upload}>
      <label>Scientific PDF<input type="file" name="file" accept="application/pdf,.pdf" required disabled={busy} onChange={() => { pendingUpload.current = null; }} /></label>
      <button className="primary-button" disabled={busy}>{busy ? "Working…" : "Upload PDF"}</button>
    </form>
    <form className="search-form" onSubmit={(event) => { event.preventDefault(); setQuery(draft); setLoading(true); setRefresh((n) => n + 1); }}>
      <label className="sr-only" htmlFor="paper-search">Search titles or filenames</label>
      <input id="paper-search" type="search" placeholder="Search titles or filenames" maxLength={200} value={draft} onChange={(event) => setDraft(event.target.value)} />
      <button className="refresh-button">Search</button>
    </form>
    {error && <p role="alert" className="error-message">{error}</p>}
    {notice && <p role="status" className="success-message">{notice}</p>}
    {loading ? <p role="status" className="muted">Loading papers…</p> : papers.length === 0 ? <p className="empty-state">{query || project ? "No papers match this selection." : "Upload your first PDF to begin your research library."}</p> : <div className="paper-list">
      {papers.map((paper) => <button className="paper-row" key={paper.id} onClick={() => open(paper)} aria-pressed={selected?.id === paper.id}>
        <span className="pdf-icon" aria-hidden="true">PDF</span><span><strong>{paper.title || paper.original_name}</strong><small>{(paper.byte_size / 1024).toFixed(1)} KB · {paper.project_ids.length} projects</small></span><span className="paper-state">{paper.processing_state.replaceAll("_", " ")}</span>
      </button>)}
    </div>}
    {cursor && <button className="refresh-button" disabled={busy} onClick={more}>Load more papers</button>}
    {selected && <section className="paper-detail" aria-label="Paper detail">
      <div className="section-heading"><h2>{selected.title || selected.original_name}</h2><button className="refresh-button" onClick={() => { setSelected(null); setDeleting(false); }}>Close</button></div>
      <p className="muted">Review extraction and create an evidence-linked analysis beside the original. AI reports require verification; Mock output tests only the workflow.</p>
      <form className="title-form" key={`${selected.id}:${selected.revision}`} onSubmit={rename}>
        <label>Paper title<input name="title" maxLength={500} defaultValue={selected.title ?? ""} placeholder="Optional title" /></label><button className="refresh-button" disabled={busy}>Save title</button>
      </form>
      <div className="toolbar"><a className="docs-link" href={`/api/v1/papers/${selected.id}/file?download=true`}>Download original</a>
        <button className="refresh-button" onClick={() => open(selected)} disabled={busy}>Reload details</button>
        <button className="refresh-button" onClick={() => setDeleting(true)} disabled={busy}>Delete paper</button></div>
      {deleting && <div className="delete-confirm"><p>Delete this paper and its original file from every project?</p><button className="danger-button" onClick={remove} disabled={busy}>Confirm paper deletion</button><button onClick={() => setDeleting(false)} disabled={busy}>Cancel</button></div>}
      <div className="document-workspace"><PdfViewer key={selected.id} paperId={selected.id} requestedPage={requestedPage} />
      <DocumentExtraction key={selected.id} paperId={selected.id} jobId={selected.latest_ingestion_job_id} session={session} expired={expired} changed={changed} sourcePage={sourcePage} /></div>
      <p className="muted">If your browser cannot preview this document, download the original PDF.</p>
    </section>}
  </section>;
}
