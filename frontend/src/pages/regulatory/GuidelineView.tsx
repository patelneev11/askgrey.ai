import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { StatusPill } from '@/components/StatusPill';
import {
  api,
  type GuidelineCheckReport,
  type GuidelineReference,
  type Jurisdiction,
  type RequirementFinding,
} from '@/lib/api';
import { getAccessToken } from '@/lib/session';

import { errorMessage } from './errors';
import { SelectField, TextAreaField, TextField } from './fields';
import styles from './regulatory.module.css';

const JURISDICTIONS: { value: Jurisdiction; label: string }[] = [
  { value: 'fda', label: 'FDA' },
  { value: 'ema', label: 'EMA' },
  { value: 'pmda', label: 'PMDA' },
];

const STATUS_CLASS: Record<RequirementFinding['status'], string> = {
  addressed: styles.addressed,
  missing: styles.missing,
  indeterminate: styles.indeterminate,
};

/** A drafted section from elsewhere in the tab, offered as the text to check. */
export interface DraftSource {
  id: string;
  label: string;
  text: string;
}

export function useGuidelines() {
  const [reference, setReference] = useState<GuidelineReference | null>(null);
  const [sectionId, setSectionId] = useState('');
  const [draftText, setDraftText] = useState('');
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>(['fda', 'ema', 'pmda']);
  const [report, setReport] = useState<GuidelineCheckReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The vintage of the shipped datasets, so the UI can state what it compared against.
  useEffect(() => {
    let live = true;
    api
      .guidelineReference(getAccessToken())
      .then((loaded) => {
        if (live) setReference(loaded);
      })
      .catch(() => {
        /* The check itself reports its own versions; a missing listing is not worth an alarm. */
      });
    return () => {
      live = false;
    };
  }, []);

  const toggleJurisdiction = useCallback((value: Jurisdiction) => {
    setJurisdictions((prev) =>
      prev.includes(value) ? prev.filter((existing) => existing !== value) : [...prev, value],
    );
  }, []);

  const submit = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      setReport(
        await api.guidelineCheck(
          {
            section_id: sectionId.trim(),
            draft_text: draftText,
            jurisdictions,
          },
          getAccessToken(),
        ),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setRunning(false);
    }
  }, [sectionId, draftText, jurisdictions]);

  return {
    reference,
    sectionId,
    setSectionId,
    draftText,
    setDraftText,
    jurisdictions,
    toggleJurisdiction,
    report,
    running,
    error,
    submit,
  };
}

export type GuidelineController = ReturnType<typeof useGuidelines>;

interface GuidelineFormProps {
  controller: GuidelineController;
  /** Sections already drafted in this tab, so the text checked is the text drafted. */
  sources: DraftSource[];
}

export function GuidelineForm({ controller, sources }: GuidelineFormProps) {
  const {
    reference,
    sectionId,
    setSectionId,
    draftText,
    setDraftText,
    jurisdictions,
    toggleJurisdiction,
    running,
    error,
    submit,
  } = controller;
  const [picked, setPicked] = useState('');

  const canSubmit =
    !running &&
    sectionId.trim().length > 0 &&
    draftText.trim().length > 0 &&
    jurisdictions.length > 0;

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextField
        label="Section id"
        value={sectionId}
        onChange={setSectionId}
        placeholder="3.2.S.4.4"
        hint="Requirements scoped to other sections are reported as out of scope rather than judged."
        maxLength={40}
        required
      />

      {sources.length > 0 && (
        <SelectField
          label="Load a section drafted in this tab"
          value={picked}
          options={[
            { value: '', label: 'Paste text below' },
            ...sources.map((source) => ({
              value: source.id,
              label: source.label,
            })),
          ]}
          onChange={(value) => {
            setPicked(value);
            const source = sources.find((candidate) => candidate.id === value);
            if (source) {
              setDraftText(source.text);
              if (!sectionId.trim()) setSectionId(source.id);
            }
          }}
        />
      )}

      <TextAreaField
        label="Draft section text"
        value={draftText}
        onChange={setDraftText}
        rows={14}
        placeholder="Paste the drafted section to compare against the encoded expectations."
      />

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Jurisdictions</legend>
        <ul className={styles.checkGrid}>
          {JURISDICTIONS.map((jurisdiction) => {
            const vintage = reference?.jurisdictions.find(
              (entry) => entry.jurisdiction === jurisdiction.value,
            );
            return (
              <li key={jurisdiction.value}>
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    checked={jurisdictions.includes(jurisdiction.value)}
                    onChange={() => toggleJurisdiction(jurisdiction.value)}
                  />
                  <span>
                    {jurisdiction.label}
                    {vintage &&
                      ` — ${vintage.requirements.length} encoded expectations, transcribed ${vintage.retrieved}`}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </fieldset>

      <p className={styles.hint}>
        This check is literal keyword-signal matching against a dated snapshot of the documents in
        docs/regulatory-sources.md. No model is involved and no regulatory site is contacted.
      </p>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <Button type="submit" variant="primary" disabled={!canSubmit}>
        {running ? 'Comparing…' : 'Compare against jurisdictions'}
      </Button>
    </form>
  );
}

function Finding({ finding }: { finding: RequirementFinding }) {
  return (
    <li className={[styles.finding, STATUS_CLASS[finding.status]].join(' ')}>
      <span className={styles.findingTitle}>
        <span className={styles.sectionId}>{finding.requirement_id}</span> {finding.title}
      </span>
      <p className={styles.flagBody}>{finding.expectation}</p>
      <p className={styles.hint}>{finding.explanation}</p>
      <a className={styles.link} href={finding.citation.url} target="_blank" rel="noreferrer">
        {finding.citation.document} ({finding.citation.document_date})
      </a>
    </li>
  );
}

export function GuidelineOutput({ controller }: { controller: GuidelineController }) {
  const { report, running } = controller;

  if (!report) {
    return (
      <EmptyState title={running ? 'Comparing…' : 'No comparison run yet'}>
        <p>
          Paste or load a drafted section and pick the jurisdictions to compare it against. Each
          encoded expectation comes back as addressed, missing, or indeterminate — with the document
          it was transcribed from.
        </p>
      </EmptyState>
    );
  }

  return (
    <div className={styles.output}>
      <p className={styles.meta}>
        {report.section_id} · {report.word_count} words · a section under{' '}
        {report.min_words_to_judge} words is too short for the engine to judge
      </p>

      {report.jurisdictions.map((jurisdiction) => {
        const grouped = {
          addressed: jurisdiction.findings.filter((finding) => finding.status === 'addressed'),
          missing: jurisdiction.findings.filter((finding) => finding.status === 'missing'),
          indeterminate: jurisdiction.findings.filter(
            (finding) => finding.status === 'indeterminate',
          ),
        };

        return (
          <section key={jurisdiction.jurisdiction} className={styles.card}>
            <div className={styles.cardHead}>
              <h3 className={styles.cardTitle}>{jurisdiction.jurisdiction.toUpperCase()}</h3>
              <div className={styles.actions}>
                <StatusPill tone="validated">{grouped.addressed.length} addressed</StatusPill>
                <StatusPill tone="warning">{grouped.missing.length} missing</StatusPill>
                <StatusPill tone="idle">{grouped.indeterminate.length} indeterminate</StatusPill>
              </div>
            </div>
            <p className={styles.meta}>
              reference {jurisdiction.version} · transcribed {jurisdiction.retrieved}
            </p>

            {(['missing', 'indeterminate', 'addressed'] as const).map((status) =>
              grouped[status].length === 0 ? null : (
                <div key={status}>
                  <h4 className={styles.subTitle}>{status}</h4>
                  <ul className={styles.list}>
                    {grouped[status].map((finding) => (
                      <Finding key={finding.requirement_id} finding={finding} />
                    ))}
                  </ul>
                </div>
              ),
            )}

            {jurisdiction.out_of_scope_requirement_ids.length > 0 && (
              <p className={styles.hint}>
                Not judged — scoped to other sections:{' '}
                {jurisdiction.out_of_scope_requirement_ids.join(', ')}
              </p>
            )}
          </section>
        );
      })}

      <p className={styles.notice}>{report.review_notice}</p>
      <p className={styles.hint}>{report.limitations}</p>
    </div>
  );
}
