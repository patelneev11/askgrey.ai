import { useCallback, useMemo, useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';
import { api } from '@/lib/api';
import { logger } from '@/lib/observability';
import {
  EXAMPLE_STRUCTURES,
  liabilityFlags,
  outcomeTone,
  smilesInputError,
  type AdmetEstimate,
  type AdmetProfile,
  type DescriptorProfile,
  type SuggestionSet,
} from '@/lib/screening';
import { getAccessToken } from '@/lib/session';

import styles from './ScreeningPage.module.css';

const LIABILITIES_ANCHOR = 'screening-liabilities';

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/** The "(predicted)" tail travels with the value, so a cropped screenshot keeps the label. */
function PredictedMark({ children = 'predicted' }: { children?: string }) {
  return <span className={styles.predictedMark}>{children}</span>;
}

function EstimateCard({ estimate }: { estimate: AdmetEstimate }) {
  return (
    <article className={styles.estimate}>
      <header className={styles.estimateHead}>
        <h4 className={styles.estimateLabel}>{estimate.label}</h4>
        <StatusPill tone={outcomeTone(estimate.outcome)}>{estimate.outcome}</StatusPill>
      </header>

      {estimate.available ? (
        <p className={styles.estimateVerdict}>
          {estimate.verdict}
          {estimate.predicted && <PredictedMark />}
        </p>
      ) : (
        <>
          <p className={styles.estimateVerdict}>
            Not available — no fabricated value is shown here.
          </p>
          <p className={styles.estimateNote}>{estimate.reason}</p>
          <p className={styles.estimateNote}>
            <span className={styles.noteLead}>Would require</span>
            {estimate.requires}
          </p>
        </>
      )}

      {estimate.inputs.length > 0 && (
        <ul className={styles.inputs}>
          {estimate.inputs.map((input) => (
            <li
              key={input.label}
              className={[styles.input, input.within ? '' : styles.inputOutside]
                .filter(Boolean)
                .join(' ')}
            >
              <span className={styles.inputLabel}>{input.label}</span>
              <span className={styles.inputValue}>{input.value_display}</span>
              <span className={styles.inputThreshold}>{input.threshold}</span>
            </li>
          ))}
        </ul>
      )}

      {estimate.scope && <p className={styles.estimateNote}>{estimate.scope}</p>}

      {/* Required on screen, not just in the payload: the basis is what makes the verdict
          readable as a rule outcome rather than a measurement. */}
      <p className={styles.basis}>
        <span className={styles.noteLead}>Model basis</span>
        {estimate.model_basis}
      </p>
      {estimate.citation && <p className={styles.citation}>{estimate.citation}</p>}
    </article>
  );
}

export function ScreeningPage() {
  const [draft, setDraft] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [descriptors, setDescriptors] = useState<DescriptorProfile | null>(null);
  const [admet, setAdmet] = useState<AdmetProfile | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionSet | null>(null);
  const [running, setRunning] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);

  const analyse = useCallback(async (smiles: string) => {
    const invalid = smilesInputError(smiles);
    if (invalid) {
      setError(invalid);
      return;
    }

    const structure = smiles.trim();
    setRunning(true);
    setError(null);
    setSuggestionError(null);
    setSuggestions(null);
    try {
      // Descriptors and ADMET are independent reads of the same structure, so they go together.
      const token = getAccessToken();
      const [profile, admetProfile] = await Promise.all([
        api.screeningDescriptors(structure, token),
        api.screeningAdmet(structure, token),
      ]);
      setDescriptors(profile);
      setAdmet(admetProfile);
      setSubmitted(structure);
    } catch (cause) {
      // The structure itself is the researcher's input; only the failure is loggable.
      logger.warn('screening.profile_failed', {});
      setError(errorMessage(cause, 'Could not profile this structure.'));
    } finally {
      setRunning(false);
    }
  }, []);

  const requestSuggestions = useCallback(async () => {
    if (!submitted) return;
    setSuggesting(true);
    setSuggestionError(null);
    try {
      setSuggestions(await api.screeningSuggestions(submitted, getAccessToken()));
    } catch (cause) {
      logger.warn('screening.suggestions_failed', {});
      setSuggestionError(errorMessage(cause, 'Could not generate suggestions.'));
    } finally {
      setSuggesting(false);
    }
  }, [submitted]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void analyse(draft);
  };

  const flags = useMemo(() => (admet ? liabilityFlags(admet) : []), [admet]);
  const affinity = descriptors?.unavailable.find((entry) => entry.key === 'binding_affinity');
  const loaded = descriptors !== null && admet !== null;

  return (
    <DualPaneWorkspace
      storageKey="screening"
      defaultRatio={0.32}
      leftLabel="Structure input"
      rightLabel="Compound profile"
      left={
        <Panel title="Structure" className={styles.fill}>
          <form className={styles.composer} onSubmit={submit}>
            <label className={styles.label} htmlFor="screening-smiles">
              SMILES
            </label>
            <textarea
              id="screening-smiles"
              className={styles.smilesInput}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void analyse(draft);
                }
              }}
              rows={3}
              spellCheck={false}
              autoComplete="off"
              placeholder="CC(=O)OC1=CC=CC=C1C(=O)O"
            />
            <Button type="submit" variant="primary" disabled={running}>
              {running ? 'Profiling…' : 'Profile structure'}
            </Button>
            <p className={styles.hint}>
              Descriptors are computed from the structure with RDKit; ADMET fields are
              classifications from published physicochemical rules. Nothing here is a measurement.
            </p>
            {error && (
              <p className={styles.error} role="alert">
                {error}
              </p>
            )}
          </form>

          <div className={styles.examples}>
            <h3 className={styles.sectionTitle}>Example structures</h3>
            <ul className={styles.exampleList}>
              {EXAMPLE_STRUCTURES.map((example) => (
                <li key={example.name}>
                  <button
                    type="button"
                    className={styles.example}
                    onClick={() => {
                      setDraft(example.smiles);
                      void analyse(example.smiles);
                    }}
                    disabled={running}
                  >
                    <span className={styles.exampleName}>{example.name}</span>
                    <span className={styles.exampleNote}>{example.note}</span>
                    <code className={styles.smiles}>{example.smiles}</code>
                  </button>
                </li>
              ))}
            </ul>
            <p className={styles.hint}>
              Published structures to try the tab with. Every value shown for them is computed from
              the structure on request — none of it is stored sample output.
            </p>
          </div>
        </Panel>
      }
      right={
        <Panel
          title={descriptors ? `${descriptors.molecular_formula} — profile` : 'Compound profile'}
          actions={
            loaded ? (
              flags.length > 0 ? (
                <a className={styles.anchor} href={`#${LIABILITIES_ANCHOR}`}>
                  <StatusPill tone="warning">
                    {flags.length} liability {flags.length === 1 ? 'flag' : 'flags'}
                  </StatusPill>
                </a>
              ) : (
                <StatusPill tone="idle">No flag from the screened list</StatusPill>
              )
            ) : undefined
          }
          className={styles.fill}
        >
          {/* Standing on the tab whether or not a profile is loaded: nothing this page can
              show is a measurement, and the band must not depend on a request succeeding. */}
          <CaveatBand label="Unvalidated">
            Every ADMET, liability and toxicity value on this page is predicted: computational
            approximations (RDKit/LLM) from published physicochemical rules and heuristics, not
            validated assay results. Expert review and experimental confirmation are required
            before any compound or series decision.
          </CaveatBand>

          {!loaded ? (
            <EmptyState title="No structure profiled yet">
              <p>
                Enter a SMILES string on the left. The profile shows RDKit descriptors, the
                drug-likeness rule sets they satisfy, liability flags, and ADMET classifications
                with the published rule each one came from.
              </p>
              <p>
                Properties that cannot be grounded — binding affinity without a target structure,
                plasma protein binding, per-isoform CYP inhibition — are reported as unavailable
                rather than estimated.
              </p>
            </EmptyState>
          ) : (
            <div className={styles.profile}>
              {/* Safety-critical content sits first, so it is on screen without scrolling on a
                  1280–1440px laptop; the header pill also anchors here. */}
              <section id={LIABILITIES_ANCHOR}>
                <h3 className={styles.sectionTitle}>Toxicity &amp; liability flags</h3>
                <CaveatBand label="Predicted">
                  Flags below are rule classifications and substructure matches to motifs reported
                  in the literature — not evidence that this compound has the liability, and their
                  absence is not evidence of safety.
                </CaveatBand>
                {flags.length > 0 ? (
                  <ul className={styles.flags}>
                    {flags.map((flag) => (
                      <li key={flag.key} className={styles.flag}>
                        <span className={styles.flagTitle}>
                          {flag.title}
                          {flag.predicted && <PredictedMark />}
                        </span>
                        <span className={styles.flagBody}>{flag.body}</span>
                        <span className={styles.flagBasis}>
                          <span className={styles.noteLead}>Model basis</span>
                          {flag.basis}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.flagEmpty}>
                    None of the screened rules or structural alerts fired for this structure. That
                    means only that no screened motif is present — it is not a safety assessment,
                    and a patch-clamp or in vivo study is the only thing that clears a compound.
                  </p>
                )}
              </section>

              <section>
                <h3 className={styles.sectionTitle}>Identity</h3>
                <dl className={styles.identityFacts}>
                  <div>
                    <dt>Canonical SMILES</dt>
                    <dd className={styles.mono}>{descriptors.canonical_smiles}</dd>
                  </div>
                  <div>
                    <dt>Molecular formula</dt>
                    <dd className={styles.mono}>{descriptors.molecular_formula}</dd>
                  </div>
                  <div>
                    <dt>InChIKey</dt>
                    <dd className={styles.mono}>{descriptors.inchikey || 'not generated'}</dd>
                  </div>
                  <div>
                    <dt>Heavy atoms</dt>
                    <dd className={styles.mono}>{descriptors.heavy_atom_count}</dd>
                  </div>
                </dl>
                {affinity && (
                  <p className={styles.unavailable}>
                    <span className={styles.noteLead}>{affinity.label}: unavailable</span>
                    {affinity.reason} Requires: {affinity.requires}
                  </p>
                )}
              </section>

              <section>
                <h3 className={styles.sectionTitle}>Computed descriptors</h3>
                <div className={styles.propertyGrid}>
                  {descriptors.descriptors.map((descriptor) => (
                    <div key={descriptor.key} className={styles.property} title={descriptor.method}>
                      <span className={styles.propertyLabel}>{descriptor.label}</span>
                      <span className={styles.propertyValue}>
                        {descriptor.display}
                        {descriptor.unit && (
                          <span className={styles.propertyUnit}> {descriptor.unit}</span>
                        )}
                      </span>
                      <span className={styles.propertyLimit}>{descriptor.method}</span>
                    </div>
                  ))}
                </div>
                <p className={styles.basis}>
                  <span className={styles.noteLead}>Basis</span>
                  {descriptors.basis}
                </p>
                <p className={styles.estimateNote}>{descriptors.caveat}</p>
              </section>

              <section>
                <h3 className={styles.sectionTitle}>Drug-likeness rule sets</h3>
                <div className={styles.ruleSets}>
                  {descriptors.rule_sets.map((ruleSet) => (
                    <article key={ruleSet.key} className={styles.ruleSet}>
                      <header className={styles.estimateHead}>
                        <h4 className={styles.estimateLabel}>{ruleSet.name}</h4>
                        <StatusPill tone={ruleSet.compliant ? 'validated' : 'warning'}>
                          {ruleSet.compliant
                            ? 'meets every threshold'
                            : `${ruleSet.violations} outside`}
                        </StatusPill>
                      </header>
                      <ul className={styles.inputs}>
                        {ruleSet.checks.map((check) => (
                          <li
                            key={check.key}
                            className={[styles.input, check.passed ? '' : styles.inputOutside]
                              .filter(Boolean)
                              .join(' ')}
                          >
                            <span className={styles.inputLabel}>{check.label}</span>
                            <span className={styles.inputValue}>{check.value_display}</span>
                            <span className={styles.inputThreshold}>{check.limit}</span>
                          </li>
                        ))}
                      </ul>
                      <p className={styles.estimateNote}>{ruleSet.description}</p>
                      <p className={styles.citation}>{ruleSet.citation}</p>
                    </article>
                  ))}
                </div>
              </section>

              <section>
                <h3 className={styles.sectionTitle}>ADMET prediction</h3>
                <CaveatBand label="Predicted">
                  {admet.caveat}
                </CaveatBand>
                <div className={styles.estimates}>
                  {admet.estimates.map((estimate) => (
                    <EstimateCard key={estimate.key} estimate={estimate} />
                  ))}
                </div>
                <p className={styles.estimateNote}>{admet.alert_caveat}</p>
              </section>

              <section>
                <h3 className={styles.sectionTitle}>Substituent suggestions</h3>
                {suggestions ? (
                  <>
                    <CaveatBand label="Unvalidated heuristics">{suggestions.caveat}</CaveatBand>
                    <ul className={styles.suggestions}>
                      {suggestions.suggestions.map((suggestion) => (
                        <li key={suggestion.title} className={styles.suggestion}>
                          <span className={styles.flagTitle}>
                            {suggestion.title}
                            <PredictedMark>heuristic</PredictedMark>
                          </span>
                          <span className={styles.flagBody}>
                            {suggestion.site} — {suggestion.transformation}
                          </span>
                          <span className={styles.flagBody}>{suggestion.rationale}</span>
                          <span className={styles.flagBody}>
                            <span className={styles.noteLead}>Expected effect</span>
                            {suggestion.expected_effect}
                          </span>
                          {suggestion.risk && (
                            <span className={styles.flagBody}>
                              <span className={styles.noteLead}>Risk</span>
                              {suggestion.risk}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                    <p className={styles.basis}>
                      <span className={styles.noteLead}>Generated by</span>
                      {suggestions.generator}
                      {suggestions.model && ` (${suggestions.model})`}
                    </p>
                  </>
                ) : (
                  <>
                    <p className={styles.estimateNote}>
                      Medicinal-chemistry heuristics for modifying this structure. Generated on
                      request because the run calls a language model, and returned as unvalidated
                      suggestions requiring chemist review — never as predicted activity.
                    </p>
                    <Button size="sm" onClick={() => void requestSuggestions()} disabled={suggesting}>
                      {suggesting ? 'Generating…' : 'Suggest modifications'}
                    </Button>
                  </>
                )}
                {suggestionError && (
                  <p className={styles.error} role="alert">
                    {suggestionError}
                  </p>
                )}
              </section>
            </div>
          )}
        </Panel>
      }
    />
  );
}
