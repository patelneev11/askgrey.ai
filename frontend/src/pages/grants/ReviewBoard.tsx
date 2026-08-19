import { useEffect, useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { SavedLibrary } from '@/components/SavedLibrary';
import { StatusPill } from '@/components/StatusPill';
import { api } from '@/lib/api';
import {
  MAX_SECTION_CHARS,
  MIN_SECTION_CHARS,
  type BoardReport,
  type PersonaReview,
  type PersonaSummary,
} from '@/lib/grants';
import { getAccessToken } from '@/lib/session';

import styles from './grants.module.css';

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'The review board did not answer.';
}

function Review({ review }: { review: PersonaReview }) {
  return (
    <li className={styles.outcome}>
      <div className={styles.outcomeHead}>
        <span className={styles.outcomeTitle}>{review.persona_name}</span>
        {/* The NIH scale runs the other way to a percentage: 1 is exceptional, 9 is poor. */}
        <StatusPill tone="idle">{review.overall_score.toFixed(1)} / 9 overall</StatusPill>
      </div>
      <p className={styles.outcomeExplanation}>{review.focus}</p>
      <table className={styles.budgetTable}>
        <thead>
          <tr>
            <th scope="col">Criterion</th>
            <th scope="col">Score</th>
            <th scope="col">Reasoning</th>
          </tr>
        </thead>
        <tbody>
          {review.scores.map((score) => (
            <tr key={score.criterion}>
              <td>{score.criterion}</td>
              <td className={styles.amount}>{score.score}</td>
              <td>{score.reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {review.strengths.length > 0 && (
        <div className={styles.adjustments}>
          <h4 className={styles.subheading}>Strengths</h4>
          <ul>
            {review.strengths.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {review.weaknesses.length > 0 && (
        <div className={styles.adjustments}>
          <h4 className={styles.subheading}>Weaknesses</h4>
          <ul>
            {review.weaknesses.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {review.comment && <p className={styles.rationale}>{review.comment}</p>}
    </li>
  );
}

/**
 * The mock review board.
 *
 * Every number here is a language model role-playing a reviewer, so the report's own `caveat`
 * field is rendered verbatim beside the scores: the panel refuses to show a study-section-looking
 * score without the sentence saying it is not one. The scale is the NIH 1-9 as the personas gave
 * it, never rescaled into a percentage that would read as a confidence.
 */
export function ReviewBoard() {
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [sectionName, setSectionName] = useState('Research Strategy');
  const [program, setProgram] = useState('SBIR');
  const [phase, setPhase] = useState('Phase I');
  const [text, setText] = useState('');
  const [report, setReport] = useState<BoardReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [personaError, setPersonaError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .reviewPersonas(getAccessToken())
      .then((result) => {
        if (live) setPersonas(result);
      })
      .catch((cause: unknown) => {
        if (live) setPersonaError(errorMessage(cause));
      });
    return () => {
      live = false;
    };
  }, []);

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      setReport(
        await api.reviewSection(
          { section_name: sectionName, program, phase, text, personas: selected },
          getAccessToken(),
        ),
      );
    } catch (cause) {
      setError(errorMessage(cause));
      setReport(null);
    } finally {
      setRunning(false);
    }
  };

  const tooShort = text.trim().length < MIN_SECTION_CHARS;

  return (
    <Panel
      title="Mock review board"
      actions={
        report && (
          <StatusPill tone="warning">Unvalidated · {report.reviews.length} personas</StatusPill>
        )
      }
    >
      <SavedLibrary<BoardReport>
        kind="grants_review_board"
        current={
          report
            ? {
                title: `${report.section_name} — mock review`,
                subtitle: `${report.reviews.length} personas · unvalidated`,
                payload: report,
              }
            : null
        }
        onOpen={(payload) => {
          setReport(payload);
          setError(null);
        }}
      />

      <CaveatBand label="Unvalidated mock review.">
        Scores and critiques are written by a language model role-playing reviewer personas. They
        are not calibrated against real NIH or SBIR reviewer scores and carry no predictive value
        for a funding decision — a qualified reviewer has to read the draft before you act on any
        of this.
      </CaveatBand>

      {personaError && (
        <p className={styles.error} role="alert">
          Reviewer personas could not be loaded: {personaError}
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <form className={styles.form} onSubmit={submit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="board-section">
            Section
          </label>
          <input
            id="board-section"
            className={styles.input}
            maxLength={200}
            value={sectionName}
            onChange={(event) => setSectionName(event.target.value)}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="board-program">
            Program
          </label>
          <input
            id="board-program"
            className={styles.input}
            maxLength={100}
            value={program}
            onChange={(event) => setProgram(event.target.value)}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="board-phase">
            Phase
          </label>
          <input
            id="board-phase"
            className={styles.input}
            maxLength={100}
            value={phase}
            onChange={(event) => setPhase(event.target.value)}
          />
        </div>

        {personas.length > 0 && (
          <fieldset className={styles.lineGroup}>
            <legend className={styles.label}>
              Reviewers (all enabled personas when none is picked)
            </legend>
            {personas.map((persona) => (
              <label className={styles.checkbox} key={persona.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(persona.id)}
                  onChange={() => toggle(persona.id)}
                />
                {persona.name} — {persona.criteria.join(', ')}
              </label>
            ))}
          </fieldset>
        )}

        <div className={styles.wideField}>
          <label className={styles.label} htmlFor="board-text">
            Draft section text
          </label>
          <textarea
            id="board-text"
            className={styles.textarea}
            rows={10}
            maxLength={MAX_SECTION_CHARS}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Paste the draft section to be critiqued."
          />
          <span className={styles.resultCount}>
            {text.trim().length} of {MIN_SECTION_CHARS} characters minimum · sent to the model
            vendor for review
          </span>
        </div>

        <div className={styles.searchActions}>
          <Button type="submit" disabled={running || tooShort}>
            {running ? 'Reviewing…' : 'Run the board'}
          </Button>
        </div>
      </form>

      {report === null ? (
        <EmptyState title="No review run yet">
          Paste a draft section and the configured personas will each critique it. Nothing is shown
          before then — a placeholder score would read as a review of your draft.
        </EmptyState>
      ) : (
        <div>
          <p className={styles.summary}>{report.summary}</p>
          <p className={styles.provenance}>
            {report.model} · personas {report.config_version} · {report.validation_status}
          </p>
          <p className={styles.rationale}>{report.caveat}</p>
          <ul className={styles.outcomes}>
            {report.reviews.map((review) => (
              <Review key={review.persona_id} review={review} />
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
