import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { StatusPill } from "@/components/StatusPill";
import {
  rowLabel,
  type Citation,
  type MatchQuality,
  type PaperRow,
} from "@/lib/extraction";

import styles from "./CitationViewer.module.css";

export interface CitationTarget {
  row: PaperRow;
  columnLabel: string;
  citation: Citation;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

// The matching rule behind the plain-language pill, kept as its tooltip. Plain language on the
// surface: the precise terms live in the technical details below, where someone auditing the
// extraction can find them without every reader having to learn them.
const MATCH_DETAIL: Record<MatchQuality, string> = {
  exact: "The quoted words appear on this page character for character.",
  normalized:
    "The quoted words appear on this page; only spacing, line breaks and hyphenation differ.",
  fuzzy:
    "Only a close match was found on this page, so the highlighted passage is approximate — read it before relying on the value.",
};

interface CitationViewerProps {
  target: CitationTarget | null;
  /** The uploaded bytes for a document, when the PDF came from this browser session. */
  fileFor?: (documentId: string) => File | undefined;
}

/**
 * Renders the cited page with pdf.js and paints the citation rectangles over it.
 *
 * pdf.js is imported lazily: it is ~1MB and only ever needed once a citation is opened.
 * Highlight geometry is in PDF points against `page_width`/`page_height`, so the overlay
 * only has to scale by the ratio the page was actually rendered at.
 */
function PdfPage({
  file,
  citation,
  zoom,
}: {
  file: File;
  citation: Citation;
  zoom: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [fitWidth, setFitWidth] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(false);
  // Widths this page has already been painted at, so a width the frame keeps returning to
  // cannot raster it again. The canvas scales to its box, so a skipped re-raster costs
  // sharpness at that size and nothing else.
  const painted = useRef({ key: "", widths: new Set<number>() });

  // The pane is resizable independently of the window, so the page has to be re-rastered
  // against the frame itself rather than against `window.resize`.
  useLayoutEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    // Whole pixels only: the observed width is fractional and oscillates by sub-pixels, which
    // would re-raster the page on every wobble.
    setFitWidth(Math.floor(frame.clientWidth));
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setFitWidth(Math.floor(entry.contentRect.width)),
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  // Zoom multiplies the fit-to-width raster: at laptop widths a whole journal page scaled
  // into a ~400px pane is not legible, so the user has to be able to magnify it.
  const width = Math.floor(fitWidth * zoom);

  useEffect(() => {
    if (width === 0) return;
    const key = `${citation.document_id}:${citation.page_number}`;
    if (painted.current.key !== key)
      painted.current = { key, widths: new Set() };
    if (painted.current.widths.has(width)) return;
    // Each run owns the document it opened: pdf.js spawns a worker per document, so a leaked one
    // keeps respawning workers and the page never paints.
    const run = { cancelled: false, doc: null as PDFDocumentProxy | null };

    const render = async () => {
      setRendered(false);
      setError(null);
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();

        const data = new Uint8Array(await file.arrayBuffer());
        const doc = await pdfjs.getDocument({ data }).promise;
        run.doc = doc;
        if (run.cancelled) return;
        const page = await doc.getPage(citation.page_number);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: width / base.width });

        const canvas = canvasRef.current;
        const context = canvas?.getContext("2d");
        if (run.cancelled || !canvas || !context) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: context, viewport }).promise;
        if (!run.cancelled) {
          painted.current.widths.add(width);
          setRendered(true);
        }
      } catch (cause) {
        if (!run.cancelled)
          setError(
            cause instanceof Error ? cause.message : "Could not render page",
          );
      }
    };

    void render();
    return () => {
      run.cancelled = true;
      void run.doc?.destroy();
    };
  }, [file, citation, width]);

  useEffect(() => {
    if (rendered) {
      highlightRef.current?.scrollIntoView({
        block: "center",
        inline: "center",
        behavior: "smooth",
      });
    }
  }, [rendered, citation]);

  const scale = width > 0 ? width / citation.page_width : 1;
  const rects = citation.rects.length > 0 ? citation.rects : [citation.bbox];

  return (
    <div className={styles.frame}>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {/* Rastering a page takes a moment, and an unlabelled blank box reads as a broken pane. */}
      {!rendered && !error && (
        <p className={styles.rendering}>
          Rendering page {citation.page_number}…
        </p>
      )}
      {/* Measured separately from the padded frame so the raster never overflows it. */}
      <div className={styles.sizer} ref={frameRef} />
      <div
        className={styles.pageStack}
        style={{ width, height: citation.page_height * scale }}
      >
        <canvas ref={canvasRef} className={styles.canvas} />
        {rects.map((rect, index) => (
          <div
            key={index}
            ref={index === 0 ? highlightRef : undefined}
            className={
              citation.match === "fuzzy"
                ? styles.highlightFuzzy
                : styles.highlight
            }
            data-testid="citation-highlight"
            style={{
              left: rect.x0 * scale,
              top: rect.top * scale,
              width: (rect.x1 - rect.x0) * scale,
              height: (rect.bottom - rect.top) * scale,
            }}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Shown when the PDF bytes are not in the browser — a paper pulled from a PMC link is
 * fetched server-side and cannot be re-fetched cross-origin, so the quote and its page
 * anchor stand in for the raster until a proxy endpoint exists.
 */
function QuoteFallback({ citation }: { citation: Citation }) {
  return (
    <div className={styles.fallback}>
      <p className={styles.fallbackNote}>
        This paper was fetched server-side, so its pages cannot be rendered here
        yet. The cited passage is reproduced verbatim below.
      </p>
      <blockquote className={styles.quote}>{citation.text}</blockquote>
      {citation.source_url && (
        <a
          className={styles.sourceLink}
          href={`${citation.source_url}#page=${citation.page_number}`}
          target="_blank"
          rel="noreferrer"
        >
          Open the source PDF at page {citation.page_number}
        </a>
      )}
    </div>
  );
}

export function CitationViewer({ target, fileFor }: CitationViewerProps) {
  const [zoom, setZoom] = useState(MIN_ZOOM);

  if (!target) {
    return (
      <div className={styles.empty}>
        <span className={styles.emptyMark} aria-hidden="true" />
        <p className={styles.emptyTitle}>No passage selected</p>
        <p className={styles.emptyBody}>
          Every cited value in the table is a link back into its paper. Select
          one to open the page it was read from, with the exact span
          highlighted.
        </p>
      </div>
    );
  }

  const { citation, row, columnLabel } = target;
  const file = fileFor?.(citation.document_id);
  const approximate = citation.match === "fuzzy";

  return (
    <div className={styles.viewer}>
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.column}>{columnLabel}</span>
          <span className={styles.paper}>{rowLabel(row)}</span>
        </div>
        <div className={styles.headerMeta}>
          <span
            className={styles.page}
            title={`Page ${citation.page_number} of the PDF.`}
          >
            page {citation.page_number}
          </span>
          <span title={MATCH_DETAIL[citation.match]}>
            {approximate ? (
              <StatusPill tone="warning">
                wording is close, not exact
              </StatusPill>
            ) : (
              <StatusPill tone="validated">quote found on this page</StatusPill>
            )}
          </span>
          {file && (
            <span className={styles.zoom}>
              <button
                type="button"
                onClick={() =>
                  setZoom((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP))
                }
                disabled={zoom <= MIN_ZOOM}
                aria-label="Zoom out"
              >
                −
              </button>
              <button
                type="button"
                onClick={() => setZoom(MIN_ZOOM)}
                className={styles.zoomLevel}
              >
                {Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                onClick={() =>
                  setZoom((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP))
                }
                disabled={zoom >= MAX_ZOOM}
                aria-label="Zoom in"
              >
                +
              </button>
            </span>
          )}
        </div>
      </header>
      {file ? (
        <PdfPage file={file} citation={citation} zoom={zoom} />
      ) : (
        <QuoteFallback citation={citation} />
      )}
      {/* Finding the quote proves where the value came from, not that it was read correctly. */}
      <p className={styles.caveat}>
        Locating the quote does not check the value: read the highlighted
        passage and confirm it yourself before relying on the extracted value.
      </p>
      <details className={styles.caveat}>
        <summary>Technical details</summary>
        page {citation.page_number} · text block {citation.block_id} · match
        quality &ldquo;
        {citation.match}&rdquo;
      </details>
    </div>
  );
}
