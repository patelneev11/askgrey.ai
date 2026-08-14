import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';

import type { CitationTarget } from '@/components/CitationViewer';

import { api, type ExportFormat } from './api';
import {
  EMPTY_TABLE,
  cellKey,
  goalLabels,
  mergeTables,
  type ExtractionCell,
  type ExtractionTable,
  type PaperRow,
} from './extraction';
import { getAccessToken } from './session';
import { WorkspaceContext, type Source, type WorkspaceContextValue } from './workspace-context';

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Extraction failed';
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
  // document_id -> the bytes the user uploaded, so the viewer can render real pages.
  const filesByDocument = useRef(new Map<string, File>());
  const goalRef = useRef(goal);
  const sourcesRef = useRef(sources);
  const runningRef = useRef(false);

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

  const addFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      // The FileList is live and the input is reset the moment this handler returns, so it has
      // to be copied here rather than inside the (deferred) state updater.
      const picked = Array.from(files).map((file) => ({
        id: `${file.name}:${file.size}:${file.lastModified}`,
        label: file.name,
        file,
      }));
      updateSources((current) => [...current, ...picked]);
    },
    [updateSources],
  );

  const addUrl = useCallback(
    (raw: string) => {
      const url = raw.trim();
      if (!url) return;
      updateSources((current) =>
        current.some((source) => source.url === url)
          ? current
          : [...current, { id: url, label: url, url }],
      );
    },
    [updateSources],
  );

  const removeSource = useCallback(
    (id: string) => updateSources((current) => current.filter((source) => source.id !== id)),
    [updateSources],
  );

  const runExtraction = useCallback(async () => {
    const trimmed = goalRef.current.trim();
    const queued = sourcesRef.current;
    if (!trimmed || queued.length === 0 || runningRef.current) return;

    runningRef.current = true;
    setRunning(true);
    setError(null);
    setPendingColumns(goalLabels(trimmed));
    const token = getAccessToken();
    const failures: string[] = [];

    // Papers are extracted one at a time so a slow or broken source never holds the whole
    // table hostage — each result lands as soon as it arrives.
    for (const source of queued) {
      try {
        const result = source.file
          ? await api.extractFromUpload(source.file, trimmed, token)
          : await api.extractFromUrl(source.url ?? '', trimmed, token);
        if (source.file) {
          for (const row of result.rows) filesByDocument.current.set(row.document_id, source.file);
        }
        setTable((current) => mergeTables(current, result));
      } catch (cause) {
        const message = errorMessage(cause);
        failures.push(message.includes(source.label) ? message : `${source.label}: ${message}`);
      }
    }

    setPendingColumns([]);
    setRunning(false);
    runningRef.current = false;
    if (failures.length > 0) setError(failures.join(' · '));
  }, []);

  const exportTable = useCallback(
    async (format: ExportFormat) => {
      setExporting(format);
      setError(null);
      try {
        const file = await api.exportTable(table, format, {}, getAccessToken());
        saveFile(file.blob, file.filename);
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setExporting(null);
      }
    },
    [table],
  );

  const selectCitation = useCallback(
    (row: PaperRow, columnKey: string, cell: ExtractionCell) => {
      if (!cell.citation) return;
      const column = table.columns.find((candidate) => candidate.key === columnKey);
      setTarget({ row, columnLabel: column?.label ?? columnKey, citation: cell.citation });
      setActiveCell(cellKey(row.document_id, columnKey));
    },
    [table.columns],
  );

  const fileFor = useCallback((documentId: string) => filesByDocument.current.get(documentId), []);

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
