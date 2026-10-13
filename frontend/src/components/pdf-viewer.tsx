"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";

export function PdfViewer({ paperId, requestedPage }: { paperId: string; requestedPage?: { number: number; request: number } }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [navigation, setNavigation] = useState({ number: 1, request: 0 });
  const page = requestedPage && requestedPage.request > navigation.request ? Math.max(1, Math.min(requestedPage.number, document?.numPages ?? requestedPage.number)) : navigation.number;
  function setPage(number: number) { setNavigation({ number, request: requestedPage?.request ?? 0 }); }
  const [zoom, setZoom] = useState(1);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let task: PDFDocumentLoadingTask | undefined;
    import("pdfjs-dist").then((pdf) => {
      if (!alive) return;
      pdf.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";
      task = pdf.getDocument({
        url: `/api/v1/papers/${paperId}/file`, withCredentials: true, enableXfa: false,
        cMapUrl: "/pdfjs/cmaps/", cMapPacked: true, standardFontDataUrl: "/pdfjs/standard_fonts/",
        wasmUrl: "/pdfjs/wasm/", maxImageSize: 16_000_000, disableAutoFetch: true,
      });
      return task.promise;
    }).then((value) => { if (alive && value) setDocument(value); }).catch(() => {
      if (alive) setError("This document cannot be previewed. Download the original to inspect it. Password-protected PDFs are not supported yet.");
    });
    return () => { alive = false; void task?.destroy(); };
  }, [paperId]);

  useEffect(() => {
    if (!document) return;
    let alive = true;
    let render: RenderTask | undefined;
    document.getPage(page).then((pdfPage) => {
      if (!alive || !canvas.current) return;
      setReady(false);
      setError("");
      const viewport = pdfPage.getViewport({ scale: zoom });
      // Keep a bounded canvas even for unusual page dimensions.
      const factor = Math.min(2, 4096 / viewport.width, 4096 / viewport.height);
      const scaled = pdfPage.getViewport({ scale: zoom * factor });
      canvas.current.width = Math.ceil(scaled.width);
      canvas.current.height = Math.ceil(scaled.height);
      canvas.current.style.width = `${viewport.width}px`;
      canvas.current.style.maxWidth = zoom > 1 ? "none" : "100%";
      render = pdfPage.render({ canvas: canvas.current, viewport: scaled, annotationMode: 0 });
      return render.promise;
    }).then(() => { if (alive) setReady(true); }).catch(() => {
      if (alive) setError("This page could not be displayed. Try downloading the original PDF.");
    });
    return () => { alive = false; render?.cancel(); };
  }, [document, page, zoom]);

  return <div className="pdf-preview">
    <div className="toolbar">
      <button className="refresh-button" disabled={!document || page <= 1} onClick={() => setPage(page - 1)}>Previous page</button>
      <span className="muted">{document ? `Page ${page} of ${document.numPages}` : "Opening PDF…"}</span>
      <button className="refresh-button" disabled={!document || page >= document.numPages} onClick={() => setPage(page + 1)}>Next page</button>
      <label>Zoom<select aria-label="PDF zoom" value={zoom} onChange={(event) => setZoom(Number(event.target.value))}><option value={0.75}>75%</option><option value={1}>100%</option><option value={1.5}>150%</option></select></label>
    </div>
    {error ? <p role="alert" className="error-message">{error}</p> : <>
      {!ready && <p className="muted" role="status">Rendering document…</p>}
      <div className="pdf-canvas-area"><canvas ref={canvas} aria-label={`Original PDF page ${page}`} role="img" /></div>
    </>}
  </div>;
}
