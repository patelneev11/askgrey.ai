import { useMemo, useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CitationViewer } from '@/components/CitationViewer';
import { Panel } from '@/components/Panel';
import { ReviewTable } from '@/components/ReviewTable';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';
import { groundedCount } from '@/lib/extraction';
import { useWorkspace } from '@/lib/workspace-context';

import styles from './LiteraturePage.module.css';

export function LiteraturePage() {
  // The workspace lives above the router so switching tabs does not discard the table.
  const {
    sources,
    goal,
    table,
    pendingColumns,
    running,
    exporting,
    error,
    target,
    activeCell,
    setGoal,
    addFiles,
    addUrl,
    removeSource,
    runExtraction,
    exportTable,
    selectCitation,
    fileFor,
  } = useWorkspace();
  const [urlDraft, setUrlDraft] = useState('');

  const submitUrl = () => {
    addUrl(urlDraft);
    setUrlDraft('');
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void runExtraction();
  };

  const grounded = useMemo(() => groundedCount(table), [table]);
  const hasTable = table.rows.length > 0 && table.columns.length > 0;
  const hasGoal = goal.trim().length > 0;
  const canRun = hasGoal && sources.length > 0 && !running;
  const blocker =
    sources.length === 0
      ? 'Add at least one paper to generate columns.'
      : hasGoal
        ? null
        : 'Describe what to pull out of the papers to generate columns.';

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
                title="Downloads review-table.xlsx — the grid plus a Sources sheet with the quote and page behind every cited value."
              >
                {exporting === 'xlsx' ? 'Exporting…' : 'Export .xlsx'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void exportTable('csv')}
                disabled={!hasTable || exporting !== null}
                title="Downloads review-table.csv — values only, with a citation column."
              >
                {exporting === 'csv' ? 'Exporting…' : 'Export .csv'}
              </Button>
            </div>
          }
          flush
        >
          <div className={styles.canvas}>
            <form className={styles.composer} onSubmit={submit}>
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
                <Button
                  type="submit"
                  variant="primary"
                  disabled={!canRun}
                  aria-describedby="generate-hint"
                >
                  {running ? 'Generating…' : 'Generate columns'}
                </Button>
              </div>

              {/* The empty state explains the goal→column model, but it is gone once a table
                  exists — this line keeps the contract on screen for every later run. */}
              <p className={styles.hint} id="generate-hint">
                {blocker ??
                  'Each phrase in the goal becomes a column, and every value that can be traced to a passage links back to the page it came from.'}
              </p>

              <div className={styles.sourceRow}>
                <input
                  aria-label="PDF or PMC link"
                  className={styles.urlInput}
                  value={urlDraft}
                  onChange={(event) => setUrlDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      submitUrl();
                    }
                  }}
                  placeholder="https://pmc.ncbi.nlm.nih.gov/articles/PMC…"
                  autoComplete="off"
                />
                <Button size="sm" onClick={submitUrl} disabled={urlDraft.trim().length === 0}>
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

              {/* The text of anything added here leaves the workspace, so say so where the
                  decision is made rather than in a policy page nobody opens. */}
              <p className={styles.hint}>
                Text from these documents is sent to Anthropic (Claude) to generate the columns.
                Do not add material you are not permitted to share with a third-party processor.
              </p>

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
                onCitationSelect={selectCitation}
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
