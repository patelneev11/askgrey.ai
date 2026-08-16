import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import type { CitationTarget } from '@/components/CitationViewer';

import { api, type ExportFormat, type StoredSource, type StoredWorkspace } from './api';
import {
  EMPTY_TABLE,
  cellKey,
  goalLabels,
  mergeTables,
  withoutRows,
  type ExtractionCell,
  type ExtractionTable,
  type PaperRow,
} from './extraction';
import { logger } from './observability';
import { getAccessToken } from './session';
import { WorkspaceContext, type Source, type WorkspaceContextValue } from './workspace-context';

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Extraction failed';
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
}

function isFetchableUrl(url: string): boolean {
  try {
    return ['http:', 'https:'].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

/** How long the workspace sits still before it is written back, so typing isn't a write storm. */
const SAVE_DEBOUNCE_MS = 800;

function toStored(source: Source): StoredSource {
  return {
    id: source.id,
    label: source.label,
    kind: source.url ? 'url' : 'upload',
    url: source.url ?? '',
    // Only the first is carried: a source is one paper, and the extra ids a merged PDF could
    // produce are recoverable from the table's rows.
    document_id: source.documentIds?.[0] ?? '',
  };
}

function fromStored(stored: StoredSource): Source {
  return {
    id: stored.id,
    label: stored.label,
    url: stored.kind === 'url' ? stored.url : undefined,
    documentIds: stored.document_id ? [stored.document_id] : undefined,
  };
}

function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [goal, setGoal] = useState('');
  const [table, setTable] = useState<ExtractionTable>(EMPTY_TABLE);
  const [pendingColumns, setPendingColumns] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<CitationTarget | null>(null);
  const [activeCell, setActiveCell] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  // document_id -> the paper's bytes, so the viewer can render real pages. An upload lands
  // here directly; a paper reached by link is pulled back from the server's stored copy.
  const [filesByDocument, setFilesByDocument] = useState<ReadonlyMap<string, File>>(new Map());
  const requestedDocuments = useRef(new Set<string>());
  const goalRef = useRef(goal);
  const sourcesRef = useRef(sources);
  const runningRef = useRef(false);

  const rememberFile = useCallback((documentId: string, file: File) => {
    requestedDocuments.current.add(documentId);
    setFilesByDocument((current) => new Map(current).set(documentId, file));
  }, []);

  const updateGoal = useCallback((next: string) => {
    goalRef.current = next;
    setGoal(next);
  }, []);

  const updateSources = useCallback((next: (current: Source[]) => Source[]) => {
    setSources((current) => {
      const updated = next(current);
      sourcesRef.current = updated;
      return updated;
    });
    // A source the user just changed can no longer be the subject of the last failure.
    setError(null);
  }, []);

  // Sources are validated as they are added: a chip says "this paper is queued", so an
  // unusable file must never get one and then fail minutes later behind an extraction run.
  const addFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      // The FileList is live and the input is reset the moment this handler returns, so it has
      // to be copied here rather than inside the (deferred) state updater.
      const chosen = Array.from(files);
      const rejected = chosen.filter((file) => !isPdf(file));
      const picked = chosen.filter(isPdf).map((file) => ({
        id: `${file.name}:${file.size}:${file.lastModified}`,
        label: file.name,
        file,
      }));
      if (picked.length > 0) updateSources((current) => [...current, ...picked]);
      if (rejected.length > 0) {
        setError(
          `${rejected.map((file) => file.name).join(', ')} is not a PDF. Upload a PDF file, or paste a link to one.`,
        );
      }
    },
    [updateSources],
  );

  const addUrl = useCallback(
    (raw: string) => {
      const url = raw.trim();
      if (!url) return;
      if (!isFetchableUrl(url)) {
        setError(`${url} is not a valid link. Paste a full https:// URL to a PDF or PMC article.`);
        return;
      }
      updateSources((current) =>
        current.some((source) => source.url === url)
          ? current
          : [...current, { id: url, label: url, url }],
      );
    },
    [updateSources],
  );

  // Removing a paper removes its findings too: a table that still counts a paper the user
  // just deleted is claiming evidence the workspace no longer holds.
  const removeSource = useCallback(
    (id: string) => {
      const removed = sourcesRef.current.find((source) => source.id === id);
      updateSources((current) => current.filter((source) => source.id !== id));
      if (!removed) return;
      setTable((current) => {
        const ids = new Set(removed.documentIds ?? []);
        for (const row of current.rows) {
          if (removed.url && row.source_url === removed.url) ids.add(row.document_id);
          if (!removed.url && row.filename === removed.label) ids.add(row.document_id);
        }
        return withoutRows(current, ids);
      });
      setTarget((current) =>
        current && (removed.documentIds ?? []).includes(current.row.document_id) ? null : current,
      );
    },
    [updateSources],
  );

  const runExtraction = useCallback(async () => {
    const trimmed = goalRef.current.trim();
    const queued = sourcesRef.current;
    if (!trimmed || queued.length === 0 || runningRef.current) return;

    runningRef.current = true;
    // The goal text is the researcher's own words, so only its size is recorded.
    logger.info('extraction.started', { sources: queued.length, goal_length: trimmed.length });
    const startedAt = performance.now();
    setRunning(true);
    setError(null);
    setPendingColumns(goalLabels(trimmed));
    const token = getAccessToken();
    const failures: string[] = [];

    // Papers are extracted one at a time so a slow or broken source never holds the whole
    // table hostage — each result lands as soon as it arrives.
    for (const source of queued) {
      try {
        let result: ExtractionTable;
        if (source.file) {
          result = await api.extractFromUpload(source.file, trimmed, token);
        } else if (source.url) {
          result = await api.extractFromUrl(source.url, trimmed, token);
        } else if (source.documentIds?.length) {
          // A restored upload: the browser no longer holds the bytes, the server does.
          result = await api.extractFromStoredDocument(source.documentIds[0], trimmed, token);
        } else {
          throw new Error('this paper is no longer available — remove it and add it again');
        }
        const documentIds = result.rows.map((row) => row.document_id);
        if (source.file) {
          for (const id of documentIds) rememberFile(id, source.file);
        }
        updateSources((current) =>
          current.map((candidate) =>
            candidate.id === source.id ? { ...candidate, documentIds } : candidate,
          ),
        );
        setTable((current) => mergeTables(current, result));
      } catch (cause) {
        const message = errorMessage(cause);
        failures.push(message.includes(source.label) ? message : `${source.label}: ${message}`);
      }
    }

    setPendingColumns([]);
    setRunning(false);
    runningRef.current = false;
    logger.info('extraction.finished', {
      sources: queued.length,
      failed: failures.length,
      duration_ms: Math.round(performance.now() - startedAt),
    });
    if (failures.length > 0) setError(failures.join(' · '));
  }, [rememberFile, updateSources]);

  const exportTable = useCallback(
    async (format: ExportFormat) => {
      setExporting(format);
      setError(null);
      try {
        const file = await api.exportTable(table, format, {}, getAccessToken());
        saveFile(file.blob, file.filename);
        logger.info('export.completed', {
          format,
          rows: table.rows.length,
          columns: table.columns.length,
        });
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setExporting(null);
      }
    },
    [table],
  );

  /**
   * Pull a paper's stored bytes back so its cited page can be drawn.
   *
   * A paper added by link never existed in the browser, and an uploaded one is gone after a
   * reload; without this the viewer can only ever show the quote and a link out.
   */
  const ensureFile = useCallback((documentId: string, label: string) => {
    if (!documentId || requestedDocuments.current.has(documentId)) return;
    requestedDocuments.current.add(documentId);
    void api
      .documentPdf(documentId, getAccessToken())
      .then((blob) => {
        const file = new File([blob], label || `${documentId}.pdf`, { type: 'application/pdf' });
        setFilesByDocument((current) => new Map(current).set(documentId, file));
      })
      .catch((cause: unknown) => {
        // The quote-and-link fallback still stands, so this is not worth an error banner.
        logger.warn('citation.pdf_unavailable', { document_id: documentId });
        logger.debug('citation.pdf_error', { message: errorMessage(cause) });
      });
  }, []);

  const selectCitation = useCallback(
    (row: PaperRow, columnKey: string, cell: ExtractionCell) => {
      if (!cell.citation) return;
      ensureFile(row.document_id, row.filename);
      const column = table.columns.find((candidate) => candidate.key === columnKey);
      setTarget({
        row,
        columnLabel: column?.label ?? columnKey,
        citation: cell.citation,
      });
      setActiveCell(cellKey(row.document_id, columnKey));
    },
    [table.columns, ensureFile],
  );

  const fileFor = useCallback(
    (documentId: string) => filesByDocument.get(documentId),
    [filesByDocument],
  );

  // Restore the saved workspace once, on sign-in: this provider mounts behind the auth gate,
  // so a reload and a fresh login both land here.
  useEffect(() => {
    let cancelled = false;
    void api
      .loadWorkspace(getAccessToken())
      .then((saved: StoredWorkspace) => {
        if (cancelled) return;
        goalRef.current = saved.goal;
        sourcesRef.current = saved.sources.map(fromStored);
        setGoal(saved.goal);
        setSources(sourcesRef.current);
        if (saved.table) setTable(saved.table);
      })
      .catch((cause: unknown) => {
        logger.warn('workspace.restore_failed', { message: errorMessage(cause) });
      })
      .finally(() => {
        if (!cancelled) setRestored(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Write the workspace back after it settles. Saving is deliberately silent: a failed save
  // must not interrupt a review, and the next edit retries it.
  useEffect(() => {
    if (!restored || running) return;
    const timer = setTimeout(() => {
      void api
        .saveWorkspace(
          {
            goal,
            sources: sources.map(toStored),
            table: table.rows.length > 0 ? table : null,
          },
          getAccessToken(),
        )
        .catch((cause: unknown) => {
          logger.warn('workspace.save_failed', { message: errorMessage(cause) });
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [restored, running, goal, sources, table]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      sources,
      goal,
      table,
      pendingColumns,
      running,
      exporting,
      error,
      target,
      activeCell,
      restored,
      setGoal: updateGoal,
      addFiles,
      addUrl,
      removeSource,
      runExtraction,
      exportTable,
      selectCitation,
      fileFor,
    }),
    [
      sources,
      goal,
      table,
      pendingColumns,
      running,
      exporting,
      error,
      target,
      activeCell,
      restored,
      updateGoal,
      addFiles,
      addUrl,
      removeSource,
      runExtraction,
      exportTable,
      selectCitation,
      fileFor,
    ],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
