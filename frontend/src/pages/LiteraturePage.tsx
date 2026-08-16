import { useMemo, useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { CitationViewer } from '@/components/CitationViewer';
import { EmptyState } from '@/components/EmptyState';
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
  // A dimmed button is not an explanation: name every prerequisite that is actually missing.
  const blocker =
    sources.length === 0 && !hasGoal
      ? 'Two things are missing: add at least one paper, and describe what to pull out of them.'
      : sources.length === 0
        ? 'Add at least one paper to generate columns.'
        : hasGoal
          ? null
          : 'Describe what to pull out of the papers to generate columns.';

  return (
    <DualPaneWorkspace
      storageKey="literature"
      // An even split: the right pane renders a whole journal page, which is illegible in the
      // ~370px a 58/42 split leaves it at 1280px.
      defaultRatio={0.5}
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
            </div>
          }
          flush
        >
          <div className={styles.canvas}>
            <form className={styles.composer} onSubmit={submit}>
              {/* Values are read out of the papers by a language model: the citation proves
                  where a value came from, never that it was read correctly. */}
              <CaveatBand label="Unvalidated">
                Every value here was extracted by a language model and is unvalidated: open the
                cited passage and confirm it against the paper before relying on it. A value with
                no citation has not been checked against any passage at all.
              </CaveatBand>

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

              {/* The full model, permanently reachable rather than only on an empty workspace. */}
              <details className={styles.howItWorks}>
                <summary>How this works</summary>
                <ol>
                  <li>
                    <strong>Add the papers.</strong> Upload PDFs, or paste a link to a PDF or PMC
                    article. Each paper becomes one row.
                  </li>
                  <li>
                    <strong>Say what you need.</strong> Write it as a list — “sample size, dosing
                    regimen, primary endpoint”. Each phrase becomes one column.
                  </li>
                  <li>
                    <strong>Check every value against its source.</strong> A value marked with a
                    page number links to that page in the paper, with the sentence it came from
                    highlighted. A value marked “no source found” could not be traced to any
                    passage, so nothing supports it yet.
                  </li>
                </ol>
              </details>

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
                <ul className={styles.sourceList} aria-label="Added papers">
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
              <EmptyState title="No columns yet">
                <p>
                  Add the papers to review, then describe what to pull out of them. Each phrase in
                  the goal becomes a column, and every value that can be traced to a passage links
                  back to the page it came from.
                </p>
              </EmptyState>
            )}

            {/* What each download contains, on screen: a tooltip is no use to someone deciding
                which of the two files to send to a colleague. */}
            <div className={styles.exports}>
              <div className={styles.exportOption}>
                <Button
                  size="sm"
                  onClick={() => void exportTable('xlsx')}
                  disabled={!hasTable || exporting !== null}
                >
                  {exporting === 'xlsx' ? 'Exporting…' : 'Export .xlsx'}
                </Button>
                <span className={styles.exportNote}>
                  Excel workbook: the table as you see it, plus a Sources sheet listing the quote
                  and page number behind every cited value.
                </span>
              </div>
              <div className={styles.exportOption}>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void exportTable('csv')}
                  disabled={!hasTable || exporting !== null}
                >
                  {exporting === 'csv' ? 'Exporting…' : 'Export .csv'}
                </Button>
                <span className={styles.exportNote}>
                  Plain spreadsheet file: one row per paper with the values and a citation column —
                  no separate Sources sheet.
                </span>
              </div>
            </div>
          </div>
        </Panel>
      }
      right={<Panel flush>{<CitationViewer target={target} fileFor={fileFor} />}</Panel>}
    />
  );
}
