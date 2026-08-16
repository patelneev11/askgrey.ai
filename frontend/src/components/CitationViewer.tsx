import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { StatusPill } from '@/components/StatusPill';
import { rowLabel, type Citation, type MatchQuality, type PaperRow } from '@/lib/extraction';

import styles from './CitationViewer.module.css';

export interface CitationTarget {
  row: PaperRow;
  columnLabel: string;
  citation: Citation;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

/** The exact matching rule behind the plain-language pill, kept as its tooltip. */
const MATCH_DETAIL: Record<MatchQuality, string> = {
  exact: 'The quote is present in the parsed page text character for character (an "exact" match).',
  normalized:
    'The quote matches the parsed page text once runs of spaces, line breaks and hyphenation are folded (a "normalized" match); the wording itself is unchanged.',
  fuzzy:
    'Only a close match was found in the parsed page text (a "fuzzy" match), so the highlighted span is approximate.',
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
function PdfPage({ file, citation, zoom }: { file: File; citation: Citation; zoom: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [fitWidth, setFitWidth] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(false);

  // The pane is resizable independently of the window, so the page has to be re-rastered
  // against the frame itself rather than against `window.resize`.
  useLayoutEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    setFitWidth(frame.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setFitWidth(entry.contentRect.width));
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  // Zoom multiplies the fit-to-width raster: at laptop widths a whole journal page scaled
  // into a ~400px pane is not legible, so the user has to be able to magnify it.
  const width = fitWidth * zoom;

  useEffect(() => {
    if (width === 0) return;
    let cancelled = false;

    const render = async () => {
      setRendered(false);
      setError(null);
      try {
        const pdfjs = await import('pdfjs-dist');
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          'pdfjs-dist/build/pdf.worker.min.mjs',
          import.meta.url,
        ).toString();

        const data = new Uint8Array(await file.arrayBuffer());
        const doc = await pdfjs.getDocument({ data }).promise;
        const page = await doc.getPage(citation.page_number);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: width / base.width });

        const canvas = canvasRef.current;
        const context = canvas?.getContext('2d');
        if (cancelled || !canvas || !context) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: context, viewport }).promise;
        if (!cancelled) setRendered(true);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Could not render page');
      }
    };

    void render();
    return () => {
      cancelled = true;
    };
  }, [file, citation, width]);

  useEffect(() => {
    if (rendered) {
      highlightRef.current?.scrollIntoView({
        block: 'center',
        inline: 'center',
        behavior: 'smooth',
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
      {/* Measured separately from the padded frame so the raster never overflows it. */}
      <div className={styles.sizer} ref={frameRef} />
      <div className={styles.pageStack} style={{ width, height: citation.page_height * scale }}>
        <canvas ref={canvasRef} className={styles.canvas} />
        {rects.map((rect, index) => (
          <div
            key={index}
            ref={index === 0 ? highlightRef : undefined}
            className={citation.match === 'fuzzy' ? styles.highlightFuzzy : styles.highlight}
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
        This paper was fetched server-side, so its pages cannot be rendered here yet. The cited
        passage is reproduced verbatim below.
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
          Every cited value in the table is a link back into its paper. Select one to open the page
          it was read from, with the exact span highlighted.
        </p>
      </div>
    );
  }

  const { citation, row, columnLabel } = target;
  const file = fileFor?.(citation.document_id);
  const approximate = citation.match === 'fuzzy';

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
            title={`Page ${citation.page_number} of the PDF, text block ${citation.block_id}.`}
          >
            page {citation.page_number}
          </span>
          <span title={MATCH_DETAIL[citation.match]}>
            {approximate ? (
              <StatusPill tone="warning">wording is close, not exact</StatusPill>
            ) : (
              <StatusPill tone="validated">quote found on this page</StatusPill>
            )}
          </span>
          {file && (
            <span className={styles.zoom}>
              <button
                type="button"
                onClick={() => setZoom((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP))}
                disabled={zoom <= MIN_ZOOM}
                aria-label="Zoom out"
              >
                −
              </button>
              <button type="button" onClick={() => setZoom(MIN_ZOOM)} className={styles.zoomLevel}>
                {Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                onClick={() => setZoom((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP))}
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
        Locating the quote does not check the value: read the highlighted passage and confirm it
        yourself before relying on the extracted value.
      </p>
    </div>
  );
}
