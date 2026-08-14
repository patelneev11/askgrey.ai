import { useCallback, useMemo, useRef, useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CitationViewer, type CitationTarget } from '@/components/CitationViewer';
import { Panel } from '@/components/Panel';
import { ReviewTable } from '@/components/ReviewTable';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';
import { api, type ExportFormat } from '@/lib/api';
import {
  EMPTY_TABLE,
  cellKey,
  groundedCount,
  mergeTables,
  type ExtractionCell,
  type ExtractionTable,
  type PaperRow,
} from '@/lib/extraction';
import { getAccessToken } from '@/lib/session';

import styles from './LiteraturePage.module.css';

interface Source {
  id: string;
  label: string;
  file?: File;
  url?: string;
}

/** Split the goal the same way the backend does, so pending headers match real columns. */
function goalLabels(goal: string): string[] {
  return goal
    .split(/[,;\n]| and (?=[a-z])/)
    .map((part) => part.trim().replace(/\s+/g, ' '))
    .filter(Boolean);
}

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

export function LiteraturePage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [urlDraft, setUrlDraft] = useState('');
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

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    // The FileList is live and the input is reset the moment this handler returns, so it has
    // to be copied here rather than inside the (deferred) state updater.
    const picked = Array.from(files).map((file) => ({
      id: `${file.name}:${file.size}:${file.lastModified}`,
      label: file.name,
      file,
    }));
    setSources((current) => [...current, ...picked]);
  };

  const addUrl = () => {
    const url = urlDraft.trim();
    if (!url) return;
    setSources((current) =>
      current.some((source) => source.url === url)
        ? current
        : [...current, { id: url, label: url, url }],
    );
    setUrlDraft('');
  };

  const removeSource = (id: string) =>
    setSources((current) => current.filter((source) => source.id !== id));

  const runExtraction = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed || sources.length === 0 || running) return;

    setRunning(true);
    setError(null);
    setPendingColumns(goalLabels(trimmed));
    const token = getAccessToken();
    const failures: string[] = [];

    // Papers are extracted one at a time so a slow or broken source never holds the whole
    // table hostage — each result lands as soon as it arrives.
    for (const source of sources) {
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
    if (failures.length > 0) setError(failures.join(' · '));
  };

  const onCitationSelect = useCallback(
    (row: PaperRow, columnKey: string, cell: ExtractionCell) => {
      if (!cell.citation) return;
      const column = table.columns.find((candidate) => candidate.key === columnKey);
      setTarget({ row, columnLabel: column?.label ?? columnKey, citation: cell.citation });
      setActiveCell(cellKey(row.document_id, columnKey));
    },
    [table.columns],
  );

  const exportTable = async (format: ExportFormat) => {
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
  };

  const fileFor = useCallback((documentId: string) => filesByDocument.current.get(documentId), []);

  const grounded = useMemo(() => groundedCount(table), [table]);
  const hasTable = table.rows.length > 0 && table.columns.length > 0;
  const canRun = goal.trim().length > 0 && sources.length > 0 && !running;

  return (
    <DualPaneWorkspace
      storageKey="literature"
      defaultRatio={0.58}
      leftLabel="Dynamic review table"
      rightLabel="Cited passage viewer"
      left={
        <Panel
          title="Evidence review"
          actions={
            <div className={styles.actions}>
              {running ? (
                <StatusPill tone="running" pulse>
                  extracting
                </StatusPill>
              ) : (
                hasTable && <StatusPill tone="validated">{grounded} cited values</StatusPill>
              )}
              <Button
                size="sm"
                onClick={() => void exportTable('xlsx')}
                disabled={!hasTable || exporting !== null}
              >
                {exporting === 'xlsx' ? 'Exporting…' : 'Export Excel'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void exportTable('csv')}
                disabled={!hasTable || exporting !== null}
              >
                {exporting === 'csv' ? 'Exporting…' : 'CSV'}
              </Button>
            </div>
          }
          flush
        >
          <div className={styles.canvas}>
            <form className={styles.composer} onSubmit={(event) => void runExtraction(event)}>
              <label className={styles.label} htmlFor="extraction-goal">
                Extraction goal
              </label>
              <div className={styles.goalRow}>
                <input
                  id="extraction-goal"
                  className={styles.goalInput}
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                  placeholder="sample size, dosing regimen, primary efficacy endpoint"
                  autoComplete="off"
                />
                <Button type="submit" variant="primary" disabled={!canRun}>
                  {running ? 'Generating…' : 'Generate columns'}
                </Button>
              </div>

              <div className={styles.sourceRow}>
                <input
                  aria-label="PDF or PMC link"
                  className={styles.urlInput}
                  value={urlDraft}
                  onChange={(event) => setUrlDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      addUrl();
                    }
                  }}
                  placeholder="https://pmc.ncbi.nlm.nih.gov/articles/PMC…"
                  autoComplete="off"
                />
                <Button size="sm" onClick={addUrl} disabled={urlDraft.trim().length === 0}>
                  Add link
                </Button>
                <label className={styles.upload}>
                  Upload PDFs
                  <input
                    type="file"
                    accept="application/pdf"
                    multiple
                    aria-label="Upload PDFs"
                    onChange={(event) => {
                      addFiles(event.target.files);
                      event.target.value = '';
                    }}
                  />
                </label>
              </div>

              {sources.length > 0 && (
                <ul className={styles.sourceList}>
                  {sources.map((source) => (
                    <li key={source.id} className={styles.sourceChip}>
                      <span className={styles.sourceLabel}>{source.label}</span>
                      <button
                        type="button"
                        className={styles.remove}
                        aria-label={`Remove ${source.label}`}
                        onClick={() => removeSource(source.id)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {error && (
                <p className={styles.error} role="alert">
                  {error}
                </p>
              )}
            </form>

            {hasTable || running || pendingColumns.length > 0 ? (
              <ReviewTable
                table={table}
                activeCell={activeCell}
                onCitationSelect={onCitationSelect}
                pendingColumns={pendingColumns}
                busy={running && table.rows.length === 0}
              />
            ) : (
              <div className={styles.empty}>
                <p className={styles.emptyTitle}>No columns yet</p>
                <p className={styles.emptyBody}>
                  Add the papers to review, then describe what to pull out of them. Each phrase in
                  the goal becomes a column, and every value that can be traced to a passage links
                  back to the page it came from.
                </p>
              </div>
            )}
          </div>
        </Panel>
      }
      right={<Panel flush>{<CitationViewer target={target} fileFor={fileFor} />}</Panel>}
    />
  );
}
