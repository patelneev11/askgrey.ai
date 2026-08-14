import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { StatusPill } from '@/components/StatusPill';
import { rowLabel, type Citation, type PaperRow } from '@/lib/extraction';

import styles from './CitationViewer.module.css';

export interface CitationTarget {
  row: PaperRow;
  columnLabel: string;
  citation: Citation;
}

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
function PdfPage({ file, citation }: { file: File; citation: Citation }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(false);

  useLayoutEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const measure = () => setWidth(frame.clientWidth);
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

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
    if (rendered) highlightRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [rendered, citation]);

  const scale = width > 0 ? width / citation.page_width : 1;
  const rects = citation.rects.length > 0 ? citation.rects : [citation.bbox];

  return (
    <div className={styles.frame} ref={frameRef}>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.pageStack} style={{ width, height: citation.page_height * scale }}>
        <canvas ref={canvasRef} className={styles.canvas} />
        {rects.map((rect, index) => (
          <div
            key={index}
            ref={index === 0 ? highlightRef : undefined}
            className={citation.match === 'exact' ? styles.highlight : styles.highlightFuzzy}
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

  return (
    <div className={styles.viewer}>
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.column}>{columnLabel}</span>
          <span className={styles.paper}>{rowLabel(row)}</span>
        </div>
        <div className={styles.headerMeta}>
          <span className={styles.page}>
            p{citation.page_number} · {citation.block_id}
          </span>
          {citation.match === 'exact' ? (
            <StatusPill tone="validated">exact match</StatusPill>
          ) : (
            <StatusPill tone="warning">{citation.match} match</StatusPill>
          )}
        </div>
      </header>
      {file ? <PdfPage file={file} citation={citation} /> : <QuoteFallback citation={citation} />}
    </div>
  );
}
