import { useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';
import {
  CHECKLIST_CATEGORY_LABEL,
  CONTROL_STATUS_LABEL,
  quantityLabel,
  type ChecklistCategory,
  type ChecklistItem,
  type ControlStatus,
} from '@/lib/protocols';
import { useProtocolWorkspace } from '@/lib/use-protocol';

import styles from './ProtocolPage.module.css';

const VOLUME_UNITS = ['uL', 'mL', 'L', 'nL'];

const CHECKLIST_ORDER: ChecklistCategory[] = ['storage', 'spin_speed', 'handling', 'timing'];

/**
 * A control finding is never emerald: emerald reads as a passed checkpoint across the product,
 * and a control the model believes is present has still not been validated by anyone.
 */
function controlTone(status: ControlStatus): 'warning' | 'idle' {
  return status === 'present' ? 'idle' : 'warning';
}

function ChecklistGroup({ category, items }: { category: ChecklistCategory; items: ChecklistItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className={styles.checklistGroup}>
      <h4 className={styles.checklistHeading}>{CHECKLIST_CATEGORY_LABEL[category]}</h4>
      <ul className={styles.checklist}>
        {items.map((item) => (
          <li key={item.id}>
            <span className={styles.checklistSubject}>{item.subject}</span>
            <span className={styles.mono}>{item.detail}</span>
            {item.quote && <span className={styles.checklistQuote}>“{item.quote}”</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ProtocolPage() {
  const workspace = useProtocolWorkspace();
  const {
    goal,
    sample,
    drafting,
    draft,
    error,
    version,
    dirty,
    saving,
    history,
    review,
    reviewing,
    checklist,
    mix,
    batchScale,
    mixResult,
    mixError,
    exportPayload,
    exporting,
    saved,
    opening,
  } = workspace;
  const [folderId, setFolderId] = useState('');

  const submitGoal = (event: FormEvent) => {
    event.preventDefault();
    void workspace.generate();
  };

  return (
    <DualPaneWorkspace
      storageKey="protocol"
      defaultRatio={0.34}
      leftLabel="Goal, controls and reagent checklist"
      rightLabel="Protocol draft"
      left={
        <Panel
          title="Draft a protocol"
          actions={
            drafting ? (
              <StatusPill tone="running" pulse>
                drafting
              </StatusPill>
            ) : (
              draft && <span className={styles.totalTime}>{draft.total_duration || '—'}</span>
            )
          }
          className={styles.fill}
        >
          <form className={styles.composer} onSubmit={submitGoal}>
            <label className={styles.label} htmlFor="protocol-goal">
              Experimental goal
            </label>
            <textarea
              id="protocol-goal"
              className={styles.goalInput}
              rows={3}
              value={goal}
              onChange={(event) => workspace.setGoal(event.target.value)}
              placeholder="Design a Western blot protocol to measure p53 expression in MCF-7 cells post-treatment"
            />
            <label className={styles.label} htmlFor="protocol-sample">
              Organism or sample (optional)
            </label>
            <input
              id="protocol-sample"
              className={styles.textInput}
              value={sample}
              onChange={(event) => workspace.setSample(event.target.value)}
              autoComplete="off"
            />
            <Button type="submit" variant="primary" disabled={drafting} fullWidth>
              {drafting ? 'Drafting…' : 'Draft protocol'}
            </Button>
          </form>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          {saved.length > 0 && (
            <div className={styles.controls}>
              <h3 className={styles.controlsTitle}>Saved protocols</h3>
              <ul className={styles.controlList}>
                {saved.map((entry) => (
                  <li key={entry.id}>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={opening}
                      onClick={() => void workspace.openSaved(entry.id)}
                    >
                      {entry.title || 'Untitled protocol'}
                    </Button>
                    <span className={styles.stepDuration}>v{entry.current_version}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft ? (
            <>
              <div className={styles.outlineHeader}>
                <h3 className={styles.controlsTitle}>Steps</h3>
                <span className={styles.stepDuration}>reorder with ↑ ↓</span>
              </div>
              <ol className={styles.outline}>
                {draft.steps.map((step, index) => (
                  <li key={step.id} className={styles.todo}>
                    <span className={styles.marker} aria-hidden="true">
                      {step.order}
                    </span>
                    <span className={styles.stepBody}>
                      <span className={styles.stepTitle}>{step.title}</span>
                      <span className={styles.stepDuration}>{step.duration || 'no timing given'}</span>
                    </span>
                    <span className={styles.moveButtons}>
                      <button
                        type="button"
                        className={styles.moveButton}
                        aria-label={`Move ${step.title} earlier`}
                        disabled={index === 0}
                        onClick={() => workspace.moveStep(index, -1)}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className={styles.moveButton}
                        aria-label={`Move ${step.title} later`}
                        disabled={index === draft.steps.length - 1}
                        onClick={() => workspace.moveStep(index, 1)}
                      >
                        ↓
                      </button>
                    </span>
                  </li>
                ))}
              </ol>

              <div className={styles.controls}>
                <div className={styles.outlineHeader}>
                  <h3 className={styles.controlsTitle}>Controls</h3>
                  <Button
                    size="sm"
                    onClick={() => void workspace.reviewControls()}
                    disabled={reviewing}
                  >
                    {reviewing ? 'Reviewing…' : 'Review controls'}
                  </Button>
                </div>
                {review ? (
                  <>
                    <p className={styles.scopeNote}>{review.scope_note}</p>
                    <ul className={styles.controlList}>
                      {review.controls.map((finding) => (
                        <li key={`${finding.kind}-${finding.name}`} className={styles.controlItem}>
                          <StatusPill tone={controlTone(finding.status)}>
                            {finding.kind} · {CONTROL_STATUS_LABEL[finding.status]}
                          </StatusPill>
                          <span className={styles.controlName}>{finding.name}</span>
                          {finding.rationale && (
                            <span className={styles.checklistQuote}>{finding.rationale}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className={styles.scopeNote}>
                    Controls have not been reviewed for this draft. Nothing on this page asserts
                    that its controls are adequate.
                  </p>
                )}
              </div>

              <div className={styles.controls}>
                <h3 className={styles.controlsTitle}>Critical reagent checklist</h3>
                <p className={styles.scopeNote}>
                  Extracted verbatim from the draft's own text — it adds no value the protocol does
                  not state.
                </p>
                {checklist.length === 0 ? (
                  <p className={styles.scopeNote}>
                    The draft states no storage temperature, spin speed, handling or timing
                    constraint to extract.
                  </p>
                ) : (
                  CHECKLIST_ORDER.map((category) => (
                    <ChecklistGroup
                      key={category}
                      category={category}
                      items={checklist.filter((item) => item.category === category)}
                    />
                  ))
                )}
              </div>
            </>
          ) : (
            <EmptyState title="No protocol drafted yet">
              Describe the experiment above. The agent drafts a structured, editable protocol; every
              step still needs a qualified researcher's review before it reaches the bench.
            </EmptyState>
          )}
        </Panel>
      }
      right={
        <Panel
          title={draft ? draft.title : 'Protocol draft'}
          actions={
            <div className={styles.docActions}>
              <span className={styles.version}>
                {version ? `v${version}${dirty ? ' · unsaved edits' : ''}` : 'unsaved draft'}
              </span>
              <Button
                size="sm"
                onClick={() => void workspace.save()}
                disabled={!draft || saving || (!dirty && version !== null)}
              >
                {saving ? 'Saving…' : 'Save version'}
              </Button>
            </div>
          }
          className={styles.fill}
          flush
        >
          <article className={styles.document}>
            {/* Never conditional on having a draft: this tab must never render a protocol-shaped
                surface without the review requirement attached to it. */}
            <CaveatBand label="Draft">
              Agent-drafted content. Requires qualified researcher review before lab use. Nothing on
              this page has been validated at the bench; the only verified numbers are the
              calculator's arithmetic, scoped to that panel.
            </CaveatBand>

            {draft ? (
              <>
                <header className={styles.docHeader}>
                  <p className={styles.eyebrow}>
                    {draft.assay_type || 'Laboratory protocol'} ·{' '}
                    {draft.origin === 'researcher_edited' ? 'researcher-edited' : 'agent-drafted'}
                  </p>
                  <h1 className={styles.docTitle}>{draft.title}</h1>
                  {draft.summary && <p className={styles.docMeta}>{draft.summary}</p>}
                </header>

                {draft.materials.length > 0 && (
                  <section>
                    <h2 className={styles.docSection}>Materials</h2>
                    <table className={styles.reagents}>
                      <thead>
                        <tr>
                          <th scope="col">Reagent</th>
                          <th scope="col">Amount</th>
                          <th scope="col">Storage</th>
                          <th scope="col">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {draft.materials.map((material) => (
                          <tr key={material.name}>
                            <th scope="row">{material.name}</th>
                            <td className={styles.mono}>{material.amount || '—'}</td>
                            <td className={styles.mono}>{material.storage || '—'}</td>
                            <td>{material.vendor_or_catalog || 'not specified'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}

                <section>
                  <h2 className={styles.docSection}>Method</h2>
                  {draft.steps.map((step) => (
                    <div key={step.id} className={styles.stepCard}>
                      <label className={styles.srOnly} htmlFor={`${step.id}-title`}>
                        Step {step.order} title
                      </label>
                      <input
                        id={`${step.id}-title`}
                        className={styles.stepTitleInput}
                        value={step.title}
                        onChange={(event) =>
                          workspace.editStep(step.id, 'title', event.target.value)
                        }
                      />
                      <label className={styles.srOnly} htmlFor={`${step.id}-instruction`}>
                        Step {step.order} instruction
                      </label>
                      <textarea
                        id={`${step.id}-instruction`}
                        className={styles.stepInstruction}
                        rows={3}
                        value={step.instruction}
                        onChange={(event) =>
                          workspace.editStep(step.id, 'instruction', event.target.value)
                        }
                      />
                      <div className={styles.stepMeta}>
                        <label className={styles.inlineLabel} htmlFor={`${step.id}-duration`}>
                          Duration
                          <input
                            id={`${step.id}-duration`}
                            className={styles.smallInput}
                            value={step.duration}
                            onChange={(event) =>
                              workspace.editStep(step.id, 'duration', event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.inlineLabel} htmlFor={`${step.id}-temperature`}>
                          Temperature
                          <input
                            id={`${step.id}-temperature`}
                            className={styles.smallInput}
                            value={step.temperature}
                            onChange={(event) =>
                              workspace.editStep(step.id, 'temperature', event.target.value)
                            }
                          />
                        </label>
                      </div>
                      {step.critical_note && (
                        <p className={styles.criticalNote}>Critical: {step.critical_note}</p>
                      )}
                    </div>
                  ))}
                </section>

                {draft.expected_outcomes.length > 0 && (
                  <section>
                    <h2 className={styles.docSection}>Expected outcomes</h2>
                    <ul className={styles.controlList}>
                      {draft.expected_outcomes.map((outcome) => (
                        <li key={outcome}>{outcome}</li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            ) : (
              <EmptyState title="The drafted protocol appears here">
                Steps are editable and reorderable once a draft exists. The calculator below works
                without one.
              </EmptyState>
            )}

            <section className={styles.calculator}>
              <h2 className={styles.docSection}>Master mix calculator</h2>
              <p className={styles.scopeNote}>
                Deterministic arithmetic only (C₁V₁ = C₂V₂ and volume scaling, exact decimals). It
                verifies the numbers in this panel and nothing else about the protocol.
              </p>
              <label className={styles.inlineLabel} htmlFor="batch-scale">
                Samples / wells
                <input
                  id="batch-scale"
                  className={styles.smallInput}
                  type="number"
                  min={1}
                  value={batchScale}
                  onChange={(event) =>
                    workspace.setBatchScale(Math.max(1, Number(event.target.value) || 1))
                  }
                />
              </label>
              <table className={styles.reagents}>
                <thead>
                  <tr>
                    <th scope="col">Component</th>
                    <th scope="col">Per reaction</th>
                    <th scope="col">Unit</th>
                    <th scope="col">Total for {batchScale}</th>
                  </tr>
                </thead>
                <tbody>
                  {mix.map((row, index) => {
                    const line = mixResult?.lines.find((entry) => entry.name === row.name.trim());
                    return (
                      <tr key={row.id}>
                        <td>
                          <label className={styles.srOnly} htmlFor={`${row.id}-name`}>
                            Component {index + 1} name
                          </label>
                          <input
                            id={`${row.id}-name`}
                            className={styles.smallInput}
                            value={row.name}
                            onChange={(event) =>
                              workspace.editMix(row.id, 'name', event.target.value)
                            }
                          />
                        </td>
                        <td>
                          <label className={styles.srOnly} htmlFor={`${row.id}-volume`}>
                            Component {index + 1} volume per reaction
                          </label>
                          <input
                            id={`${row.id}-volume`}
                            className={styles.smallInput}
                            value={row.volume}
                            onChange={(event) =>
                              workspace.editMix(row.id, 'volume', event.target.value)
                            }
                          />
                        </td>
                        <td>
                          <label className={styles.srOnly} htmlFor={`${row.id}-unit`}>
                            Component {index + 1} unit
                          </label>
                          <select
                            id={`${row.id}-unit`}
                            className={styles.smallInput}
                            value={row.unit}
                            onChange={(event) =>
                              workspace.editMix(row.id, 'unit', event.target.value)
                            }
                          >
                            {VOLUME_UNITS.map((unit) => (
                              <option key={unit} value={unit}>
                                {unit}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className={styles.mono} data-testid={`${row.id}-total`}>
                          {line ? quantityLabel(line.total_volume) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className={styles.docActions}>
                <Button size="sm" variant="ghost" onClick={workspace.addMixRow}>
                  Add component
                </Button>
                {/* The only emerald pill on this page, and it names its own scope: the
                    arithmetic in this panel, not the protocol around it. */}
                {mixResult && <StatusPill tone="validated">Arithmetic verified · this panel only</StatusPill>}
                {mixResult && (
                  <span className={styles.mono} data-testid="mix-total">
                    Mix total {quantityLabel(mixResult.total_volume)} · includes{' '}
                    {mixResult.overage_percent}% overage
                  </span>
                )}
              </div>
              {mixError && (
                <p className={styles.error} role="alert">
                  {mixError}
                </p>
              )}
            </section>

            <section className={styles.calculator}>
              <h2 className={styles.docSection}>ELN export</h2>
              <p className={styles.scopeNote}>
                Benchling entry format, built from public API documentation and never run against a
                live Benchling account. It produces the payload for review — it does not create an
                entry.
              </p>
              <div className={styles.docActions}>
                <label className={styles.inlineLabel} htmlFor="benchling-folder">
                  Benchling folder id
                  <input
                    id="benchling-folder"
                    className={styles.smallInput}
                    value={folderId}
                    onChange={(event) => setFolderId(event.target.value)}
                    placeholder="lib_..."
                    autoComplete="off"
                  />
                </label>
                <Button
                  size="sm"
                  onClick={() => void workspace.exportEln(folderId)}
                  disabled={!draft || exporting || folderId.trim() === ''}
                >
                  {exporting ? 'Building…' : 'Export to ELN format'}
                </Button>
                <StatusPill tone="warning">Untested against live API</StatusPill>
              </div>
              {exportPayload && (
                <div className={styles.exportResult}>
                  <p className={styles.scopeNote} data-testid="export-status">
                    {exportPayload.endpoint} · {exportPayload.integration_status}
                  </p>
                  <pre className={styles.payload}>
                    {JSON.stringify({ entry: exportPayload.entry, notes: exportPayload.notes }, null, 2)}
                  </pre>
                </div>
              )}
            </section>

            {history && history.versions.length > 0 && (
              <section className={styles.calculator}>
                <h2 className={styles.docSection}>Edit history</h2>
                <ul className={styles.controlList}>
                  {history.versions.map((entry) => (
                    <li key={entry.version}>
                      <span className={styles.mono}>v{entry.version}</span> {entry.change_summary}
                      {entry.changes.length > 0 && (
                        <ul className={styles.checklist}>
                          {entry.changes.map((change) => (
                            <li key={change.field}>
                              {change.label} <span className={styles.mono}>({change.kind})</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </article>
        </Panel>
      }
    />
  );
}
