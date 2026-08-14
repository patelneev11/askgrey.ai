import { PageCanvas } from '@/components/PageCanvas';

import styles from './AuditPage.module.css';

interface Event {
  time: string;
  actor: string;
  action: string;
  target: string;
  kind: 'agent' | 'human' | 'export';
  hash: string;
}

const EVENTS: Event[] = [
  {
    time: '14:22:08',
    actor: 'Literature agent',
    action: 'Ran Entrez query',
    target: '238 hits → 12 screened · translated by claude-sonnet-4-5',
    kind: 'agent',
    hash: '9f3c1ab',
  },
  {
    time: '14:19:44',
    actor: 'Neev Patel',
    action: 'Edited review table filter',
    target: 'literature/evidence · n ≥ 200',
    kind: 'human',
    hash: '2be7740',
  },
  {
    time: '13:58:02',
    actor: 'Screening agent',
    action: 'Raised toxicity flag',
    target: 'AG-0412 · hERG 0.58 above 0.40 threshold',
    kind: 'agent',
    hash: 'c10d55e',
  },
  {
    time: '13:41:37',
    actor: 'Dana Okoye',
    action: 'Exported protocol to Benchling',
    target: 'Cytotoxicity screen v4 · entity bfi_28841',
    kind: 'export',
    hash: '77a0e93',
  },
  {
    time: '11:07:15',
    actor: 'Regulatory agent',
    action: 'Detected discrepancy',
    target: 'M2 §2.6.6 NOAEL vs M4 §4.2.3 toxicology report',
    kind: 'agent',
    hash: 'd4419c2',
  },
  {
    time: '09:52:30',
    actor: 'Marc Rehnquist',
    action: 'Accepted agent revision',
    target: 'IND module 2.4 · nonclinical overview',
    kind: 'human',
    hash: '6ea8f51',
  },
];

const FILTERS = ['All activity', 'Agent runs', 'Human edits', 'Exports'];

export function AuditPage() {
  return (
    <PageCanvas
      title="Audit Trails"
      description="Every agent run, document access and export, recorded with the model and inputs that produced it."
      actions={
        <div className={styles.filters}>
          {FILTERS.map((filter, index) => (
            <button
              key={filter}
              type="button"
              className={[styles.filter, index === 0 ? styles.filterActive : '']
                .filter(Boolean)
                .join(' ')}
            >
              {filter}
            </button>
          ))}
        </div>
      }
    >
      <p className={styles.day}>Today · August 13, 2026</p>
      <ol className={styles.timeline}>
        {EVENTS.map((event) => (
          <li key={event.hash} className={styles.event}>
            <time className={styles.time}>{event.time}</time>
            <span className={[styles.rail, styles[event.kind]].join(' ')} aria-hidden="true" />
            <div className={styles.body}>
              <p className={styles.line}>
                <span className={styles.actor}>{event.actor}</span>
                <span className={styles.action}>{event.action}</span>
              </p>
              <p className={styles.target}>{event.target}</p>
            </div>
            <code className={styles.hash}>{event.hash}</code>
          </li>
        ))}
      </ol>
      <p className={styles.retention}>
        Entries are append-only and retained for 7 years to satisfy 21 CFR Part 11.
      </p>
    </PageCanvas>
  );
}
