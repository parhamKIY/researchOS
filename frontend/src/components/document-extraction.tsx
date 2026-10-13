"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";

type Job = { id: string; state: string; stage: string | null; progress_percent: number; error: { code: string } | null };
type Version = { id: string; state: string; created_at: string; parser_name: string; parser_version: string; metadata: Record<string, unknown>; warnings: string[]; page_count: number; figure_count: number };
type VersionList = { items: Version[]; next_cursor: string | null };
type ExtractedPage = { page_number: number; text: string; text_status: string; warnings: string[] };
type Span = { page_number: number; start_offset: number; end_offset: number };
type Section = { id: string; heading: string | null; kind: string; spans: Span[] };
type Figure = { id: string; file_url: string; page_number: number; caption: string | null; caption_start: number | null; caption_end: number | null; bounding_box: number[] | null };

export function DocumentExtraction({ paperId, jobId, session, expired, changed, sourcePage }: {
  paperId: string; jobId: string | null; session: Session; expired: () => void; changed: () => void; sourcePage: (number: number) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [page, setPage] = useState<ExtractedPage | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [figures, setFigures] = useState<Figure[]>([]);
  const [figureOffset, setFigureOffset] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [span, setSpan] = useState<Span | null>(null);
  const pending = useRef<{ route: string; key: string } | null>(null);
  const observed = useRef("");
  const version = versions.find((item) => item.id === selected);
  const active = job?.state === "queued" || job?.state === "running";

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<VersionList>(`/papers/${paperId}/document-versions`);
        const current = jobId ? await api<Job>(`/jobs/${jobId}`) : null;
        if (!alive) return;
        setVersions(result.items); setCursor(result.next_cursor); setJob(current); setError("");
        setSelected((previous) => previous || result.items[0]?.id || "");
        if (current && current.state !== "queued" && current.state !== "running" && observed.current !== current.id) {
          observed.current = current.id; changed();
        }
        if (current?.state === "queued" || current?.state === "running") timer = setTimeout(poll, 1500);
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiFailure && err.status === 401) expired();
        else { setError((err as Error).message); timer = setTimeout(poll, 5000); }
      }
    }
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [paperId, jobId, refresh, expired, changed]);

  useEffect(() => {
    if (!version?.page_count) return;
    let alive = true;
    api<ExtractedPage>(`/document-versions/${selected}/pages/${pageNumber}`).then((value) => {
      if (alive) setPage(value);
    }).catch((err) => { if (alive) { if (err instanceof ApiFailure && err.status === 401) expired(); else setError(err.message); } });
    return () => { alive = false; };
  }, [selected, pageNumber, version?.page_count, expired]);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    Promise.all([
      api<{ items: Section[] }>(`/document-versions/${selected}/sections`),
      api<{ items: Figure[]; next_offset: number | null }>(`/papers/${paperId}/figures?document_version_id=${selected}`),
    ]).then(([structure, images]) => {
      if (alive) { setSections(structure.items); setFigures(images.items); setFigureOffset(images.next_offset); }
    }).catch((err) => { if (alive) { if (err instanceof ApiFailure && err.status === 401) expired(); else setError(err.message); } });
    return () => { alive = false; };
  }, [paperId, selected, version?.figure_count, version?.state, expired]);

  function failure(err: unknown) {
    if (err instanceof ApiFailure && err.status === 401) expired();
    else setError((err as Error).message);
  }

  async function process() {
    const route = job?.state === "failed" ? `/jobs/${job.id}/retry` : `/papers/${paperId}/ingestions`;
    if (pending.current?.route !== route) pending.current = { route, key: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const result = await api<Job>(route, { method: "POST", body: "{}", headers: { "Idempotency-Key": pending.current.key } }, session.csrf_token);
      setJob(result); setSelected(""); setPage(null); setSpan(null); setPageNumber(1);
      pending.current = null; changed(); setRefresh((value) => value + 1);
    } catch (err) { failure(err); }
    finally { setBusy(false); }
  }

  async function moreVersions() {
    try {
      const result = await api<VersionList>(`/papers/${paperId}/document-versions?cursor=${encodeURIComponent(cursor!)}`);
      setVersions((values) => [...values, ...result.items]); setCursor(result.next_cursor);
    } catch (err) { failure(err); }
  }

  async function moreFigures() {
    try {
      const result = await api<{ items: Figure[]; next_offset: number | null }>(`/papers/${paperId}/figures?document_version_id=${selected}&offset=${figureOffset}`);
      setFigures((values) => [...values, ...result.items]); setFigureOffset(result.next_offset);
    } catch (err) { failure(err); }
  }

  function jump(number: number, evidence: Span | null = null) {
    setPageNumber(number); setPage(null); setSpan(evidence); sourcePage(number);
  }

  return <section className="extraction-panel" aria-label="Document extraction">
    <div className="section-heading"><h3>Document extraction</h3><button className="refresh-button" disabled={busy || active} onClick={process}>{job?.state === "failed" ? "Retry extraction" : versions.length ? "Extract new version" : "Extract document"}</button></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    {job && <div role="status"><p>{job.state.replaceAll("_", " ")} · {job.progress_percent}%{active && job.stage ? ` · ${job.stage.replaceAll("_", " ")}` : ""}</p>{active && <progress max={100} value={job.progress_percent} aria-label="Extraction progress" />}{job.error && <p className="error-message">Extraction failed: {job.error.code.replaceAll("_", " ")}. The original PDF is available.</p>}</div>}
    <p className="muted">Extraction runs locally. Scanned pages need OCR, which is not available yet. Reading order, section labels and caption associations require inspection. Vector figures and structured tables are not extracted.</p>
    {versions.length > 0 && <label>Extraction history<select aria-label="Extraction history" value={selected} onChange={(event) => { setSelected(event.target.value); setPageNumber(1); setPage(null); setSpan(null); setSections([]); setFigures([]); }}>
      {versions.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {item.state.replaceAll("_", " ")}</option>)}
    </select></label>}
    {cursor && <button className="refresh-button" onClick={moreVersions}>Older versions</button>}
    {version && <>
      <p className="muted">{version.page_count} pages · {version.figure_count} raster images · Parser: {version.parser_name} ({version.parser_version})</p>
      <details><summary>Extraction warnings and unverified PDF metadata</summary><ul>{version.warnings.map((warning) => <li key={warning}>{warning.replaceAll("_", " ")}</li>)}</ul><pre>{JSON.stringify(version.metadata, null, 2)}</pre></details>
      {version.page_count > 0 && <>
        <div className="toolbar"><button className="refresh-button" disabled={pageNumber <= 1} onClick={() => jump(pageNumber - 1)}>Previous text page</button><span>Text page {pageNumber} of {version.page_count}</span><button className="refresh-button" disabled={pageNumber >= version.page_count} onClick={() => jump(pageNumber + 1)}>Next text page</button><button className="refresh-button" onClick={() => sourcePage(pageNumber)}>View source page</button></div>
        {page?.page_number === pageNumber ? <><p className="muted">Text: {page.text_status.replaceAll("_", " ")}{page.warnings.length ? ` · ${page.warnings.join(", ").replaceAll("_", " ")}` : ""}</p><pre className="extracted-text">{span ? <>{page.text.slice(0, span.start_offset)}<mark>{page.text.slice(span.start_offset, span.end_offset)}</mark>{page.text.slice(span.end_offset)}</> : page.text || "No usable text on this page."}</pre></> : <p role="status">Loading extracted text…</p>}
        <details><summary>Detected sections ({sections.length})</summary><p className="muted">Heading patterns are candidates. Offsets refer to the stored Unicode page text, starting at zero; the end is excluded.</p>{sections.map((section) => <div key={section.id}><strong>{section.heading || section.kind}</strong><div className="toolbar">{section.spans.map((evidence) => <button className="refresh-button" key={`${evidence.page_number}:${evidence.start_offset}`} onClick={() => jump(evidence.page_number, evidence)}>Page {evidence.page_number} · {evidence.start_offset}–{evidence.end_offset}</button>)}</div></div>)}</details>
      </>}
      {figures.length > 0 && <details open><summary>Extracted raster images</summary><div className="figure-grid">{figures.map((figure) => <figure key={figure.id}>
        {/* Authenticated private image; keep its original server URL. */}
        <img loading="lazy" src={figure.file_url} alt={figure.caption || `Extracted raster image from page ${figure.page_number}`} />
        <figcaption>{figure.caption ? `Candidate caption: ${figure.caption}` : "No caption association available."}</figcaption>
        <button className="refresh-button" onClick={() => jump(figure.page_number, figure.caption_start !== null && figure.caption_end !== null ? { page_number: figure.page_number, start_offset: figure.caption_start, end_offset: figure.caption_end } : null)}>View source page {figure.page_number}</button>
        {figure.bounding_box && <small>Page coordinates: {figure.bounding_box.map((value) => value.toFixed(1)).join(", ")} pt</small>}
      </figure>)}</div>{figureOffset !== null && <button className="refresh-button" onClick={moreFigures}>More images</button>}</details>}
    </>}
  </section>;
}
