import { Meter } from '@/components/Meter';
import { StatusPill } from '@/components/StatusPill';

import styles from './GrantsPage.module.css';

interface Opportunity {
  agency: string;
  code: string;
  title: string;
  ceiling: string;
  deadline: string;
  daysLeft: number;
  match: number;
}

const OPPORTUNITIES: Opportunity[] = [
  {
    agency: 'NIH / NIDDK',
    code: 'PA-24-118',
    title: 'Small Business Innovation Research (R43/R44) — metabolic disease therapeutics',
    ceiling: '$2.3M',
    deadline: 'Sep 5, 2026',
    daysLeft: 23,
    match: 0.92,
  },
  {
    agency: 'NSF',
    code: 'SBIR Phase I',
    title: 'Biological and chemical technologies, translational research',
    ceiling: '$305K',
    deadline: 'Oct 1, 2026',
    daysLeft: 49,
    match: 0.71,
  },
  {
    agency: 'NIH / NCATS',
    code: 'RFA-TR-25-004',
    title: 'Translational science of preclinical safety prediction',
    ceiling: '$1.1M',
    deadline: 'Nov 14, 2026',
    daysLeft: 93,
    match: 0.64,
  },
];

interface Reviewer {
  persona: string;
  focus: string;
  overall: string;
  verdict: 'Fund' | 'Revise' | 'Reject';
  criteria: {
    label: string;
    value: string;
    fraction: number;
    tone: 'success' | 'warning' | 'pipeline';
  }[];
  comment: string;
}

const BOARD: Reviewer[] = [
  {
    persona: 'Reviewer 1',
    focus: 'Pharmacology',
    overall: '2.1',
    verdict: 'Fund',
    criteria: [
      { label: 'Significance', value: '2', fraction: 0.9, tone: 'success' },
      { label: 'Innovation', value: '2', fraction: 0.9, tone: 'success' },
      { label: 'Approach', value: '3', fraction: 0.7, tone: 'pipeline' },
    ],
    comment:
      'Target rationale is well supported by the cited STEP trial evidence. Aim 2 milestones are measurable.',
  },
  {
    persona: 'Reviewer 2',
    focus: 'Translational safety',
    overall: '3.4',
    verdict: 'Revise',
    criteria: [
      { label: 'Significance', value: '2', fraction: 0.9, tone: 'success' },
      { label: 'Innovation', value: '4', fraction: 0.5, tone: 'warning' },
      { label: 'Approach', value: '4', fraction: 0.5, tone: 'warning' },
    ],
    comment:
      'The hERG liability flagged in screening is not addressed in the risk section; add a mitigation plan and a patch-clamp milestone.',
  },
  {
    persona: 'Reviewer 3',
    focus: 'Commercialization',
    overall: '2.8',
    verdict: 'Revise',
    criteria: [
      {
        label: 'Commercial potential',
        value: '2',
        fraction: 0.9,
        tone: 'success',
      },
      { label: 'Team', value: '3', fraction: 0.7, tone: 'pipeline' },
      { label: 'Budget realism', value: '4', fraction: 0.5, tone: 'warning' },
    ],
    comment:
      'Personnel costs consume 74% of the direct budget with no contract-research line for the tox package.',
  },
];

const BUDGET = [
  {
    label: 'Personnel',
    value: '$412,000',
    fraction: 0.74,
    tone: 'warning' as const,
  },
  {
    label: 'Contract research',
    value: '$88,000',
    fraction: 0.16,
    tone: 'pipeline' as const,
  },
  {
    label: 'Materials & supplies',
    value: '$36,000',
    fraction: 0.06,
    tone: 'pipeline' as const,
  },
  {
    label: 'Travel & dissemination',
    value: '$22,000',
    fraction: 0.04,
    tone: 'pipeline' as const,
  },
];

export function GrantsPage() {
  return (
    <div className={styles.board}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Grants</h1>
          <p className={styles.description}>
            Open federal opportunities scored against the workspace's research focus.
          </p>
        </div>
        <div className={styles.headerMeta}>
          <StatusPill tone="idle">Sample data · /api/grants not wired up yet</StatusPill>
          <span className={styles.headerStat}>3 opportunities shown</span>
        </div>
      </header>

      <section>
        <h2 className={styles.sectionTitle}>Matched opportunities</h2>
        <div className={styles.opportunities}>
          {OPPORTUNITIES.map((opportunity) => (
            <article key={opportunity.code} className={styles.opportunity}>
              <div className={styles.opportunityHead}>
                <span className={styles.agency}>{opportunity.agency}</span>
                <span className={styles.matchScore}>
                  {Math.round(opportunity.match * 100)}% fit
                </span>
              </div>
              <h3 className={styles.opportunityTitle}>{opportunity.title}</h3>
              <code className={styles.code}>{opportunity.code}</code>
              <dl className={styles.opportunityFacts}>
                <div>
                  <dt>Ceiling</dt>
                  <dd>{opportunity.ceiling}</dd>
                </div>
                <div>
                  <dt>Deadline</dt>
                  <dd>{opportunity.deadline}</dd>
                </div>
              </dl>
              <div className={styles.countdown}>
                <span
                  className={opportunity.daysLeft < 30 ? styles.urgent : styles.calm}
                  style={{
                    width: `${Math.max(4, 100 - opportunity.daysLeft)}%`,
                  }}
                />
              </div>
              <span className={styles.daysLeft}>{opportunity.daysLeft} days remaining</span>
            </article>
          ))}
        </div>
      </section>

      <div className={styles.split}>
        <section>
          <h2 className={styles.sectionTitle}>Mock review board — SBIR Phase I draft</h2>
          <div className={styles.reviewers}>
            {BOARD.map((reviewer) => (
              <article key={reviewer.persona} className={styles.reviewer}>
                <header className={styles.reviewerHead}>
                  <div>
                    <span className={styles.persona}>{reviewer.persona}</span>
                    <span className={styles.focus}>{reviewer.focus}</span>
                  </div>
                  <div className={styles.scoreBlock}>
                    <span className={styles.score}>{reviewer.overall}</span>
                    <span
                      className={
                        reviewer.verdict === 'Fund' ? styles.verdictFund : styles.verdictRevise
                      }
                    >
                      {reviewer.verdict}
                    </span>
                  </div>
                </header>
                <div className={styles.criteria}>
                  {reviewer.criteria.map((criterion) => (
                    <Meter key={criterion.label} {...criterion} />
                  ))}
                </div>
                <p className={styles.comment}>{reviewer.comment}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.budget}>
          <h2 className={styles.sectionTitle}>Budget structure</h2>
          <div className={styles.budgetCard}>
            <div className={styles.budgetTotal}>
              <span className={styles.budgetAmount}>$558,000</span>
              <span className={styles.budgetLabel}>Direct costs, 12 months</span>
            </div>
            <div className={styles.budgetLines}>
              {BUDGET.map((line) => (
                <Meter key={line.label} {...line} />
              ))}
            </div>
            <p className={styles.budgetNote}>
              Reviewer 3 flags the personnel share as high for a Phase I; shifting the tox package
              to a contract line would move it inside the typical 60–65% band.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
