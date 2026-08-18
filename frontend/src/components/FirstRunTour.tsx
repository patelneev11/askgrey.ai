import { useEffect, useRef } from 'react';

import { Button } from '@/components/Button';
import { useOnboarding } from '@/lib/onboarding-context';

import styles from './FirstRunTour.module.css';

interface Step {
  eyebrow: string;
  title: string;
  body: string;
  /** The honest qualifier for this step. Rendered in amber, never omitted. */
  caveat?: string;
}

/**
 * Four screens, roughly twenty seconds each. Anything longer is read by nobody, and the
 * per-tab notices carry the detail that matters at the moment it matters.
 */
const STEPS: Step[] = [
  {
    eyebrow: 'What this is',
    title: 'A research workspace with its sources attached',
    body: 'AskGrey runs agents over literature, compounds, trials and grant calls. Every tab is the same shape: the agent works on the left, the evidence it used sits on the right, so you can check a claim without leaving the page.',
  },
  {
    eyebrow: 'Start here',
    title: 'Literature turns a question into a table',
    body: 'Add papers as PDFs or PMC links, describe what to pull out of them in plain English, and each phrase becomes a column. Click any value to jump to the exact passage it came from, then export the table to Excel with those citations intact.',
  },
  {
    eyebrow: 'What is real today',
    title: 'The five research tabs are live; the admin pages are not',
    body: 'Literature, Screening, Protocol, Regulatory and Grants all run against real services on the data you enter, as do the PubMed, PubChem, ClinicalTrials.gov, grants.gov and SBIR searches behind them. Workspace, Audit and Settings are still read-only previews of the org, activity and configuration model.',
    caveat: 'Anything marked Sample data is illustrative. Do not read it as a result.',
  },
  {
    eyebrow: 'Before you trust it',
    title: 'The agent drafts; you remain the reviewer',
    body: 'Extracted values carry the quote and page behind them, and anything the agent could not ground is marked “no source found” rather than quietly shown as fact. Document text you add is sent to Anthropic to generate columns.',
    caveat:
      'Predicted affinity, ADMET and toxicity figures are computational approximations, not assay results, and drafted protocols and regulatory text require qualified review.',
  },
];

export function FirstRunTour() {
  const { tour, step, goToStep, skipTour, completeTour } = useOnboarding();
  const dialogRef = useRef<HTMLDivElement>(null);
  const open = tour === 'unseen';
  // A stored step from an older, longer tour must not strand the user past the last screen.
  const index = Math.min(step, STEPS.length - 1);
  const current = STEPS[index];
  const last = index === STEPS.length - 1;

  useEffect(() => {
    if (open) dialogRef.current?.focus();
  }, [open, index]);

  if (!open) return null;

  return (
    <div className={styles.scrim} role="presentation">
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="first-run-title"
        tabIndex={-1}
        ref={dialogRef}
        onKeyDown={(event) => {
          // Escape is the fastest way out, and skipping is always allowed.
          if (event.key === 'Escape') skipTour();
        }}
      >
        <div className={styles.head}>
          <span className={styles.eyebrow}>{current.eyebrow}</span>
          <span className={styles.count}>
            {index + 1} of {STEPS.length}
          </span>
        </div>

        <h2 className={styles.title} id="first-run-title">
          {current.title}
        </h2>
        <p className={styles.body}>{current.body}</p>
        {current.caveat && (
          <p className={styles.caveat} role="note">
            {current.caveat}
          </p>
        )}

        <div className={styles.progress} aria-hidden="true">
          {STEPS.map((entry, position) => (
            <span
              key={entry.title}
              className={[styles.dot, position <= index ? styles.dotActive : '']
                .filter(Boolean)
                .join(' ')}
            />
          ))}
        </div>

        <div className={styles.actions}>
          <Button variant="ghost" size="sm" onClick={skipTour}>
            Skip
          </Button>
          <div className={styles.advance}>
            {index > 0 && (
              <Button size="sm" onClick={() => goToStep(index - 1)}>
                Back
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={() => (last ? completeTour() : goToStep(index + 1))}
            >
              {last ? 'Start working' : 'Next'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
