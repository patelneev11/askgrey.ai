import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import styles from './LiteraturePage.module.css';

interface Turn {
  role: 'researcher' | 'agent';
  body: string;
  citations?: string[];
}

const THREAD: Turn[] = [
  {
    role: 'researcher',
    body: 'Randomized trials of semaglutide for obesity in adults without diabetes, 2021 onwards. Summarize weight-loss endpoints.',
  },
  {
    role: 'agent',
    body: 'Translated to a Boolean Entrez query over MeSH descriptors and title/abstract synonyms, then screened 238 hits down to 12 randomized trials with a body-weight primary endpoint. The review table on the right is built from those 12; every cell links to the passage it came from.',
    citations: ['PMID 33567185', 'PMID 35441470', 'PMID 40353578'],
  },
  {
    role: 'researcher',
    body: 'Drop anything with fewer than 200 participants.',
  },
  {
    role: 'agent',
    body: 'Four trials fall below that threshold. Filtering them out leaves 8 studies and does not change the pooled direction of effect.',
  },
];

const QUERY_CHIPS = [
  '"Semaglutide"[MeSH Terms]',
  '"Obesity"[MeSH Terms]',
  '"Randomized Controlled Trial"[Publication Type]',
  '2021/01/01 : 3000',
];

interface Row {
  study: string;
  design: string;
  n: string;
  endpoint: string;
  effect: string;
  source: string;
}

const ROWS: Row[] = [
  {
    study: 'STEP 1 (Wilding 2021)',
    design: 'Phase 3, double-blind',
    n: '1961',
    endpoint: 'Δ body weight, wk 68',
    effect: '−14.9%',
    source: 'NEJM 384:989',
  },
  {
    study: 'STEP 2 (Davies 2021)',
    design: 'Phase 3, T2D cohort',
    n: '1210',
    endpoint: 'Δ body weight, wk 68',
    effect: '−9.6%',
    source: 'Lancet 397:971',
  },
  {
    study: 'STEP 4 (Rubino 2021)',
    design: 'Withdrawal RCT',
    n: '803',
    endpoint: 'Δ weight after wk 20',
    effect: '−7.9%',
    source: 'JAMA 325:1414',
  },
  {
    study: 'STEP 1 extension (2022)',
    design: 'Off-treatment follow-up',
    n: '327',
    endpoint: 'Regain, wk 68→120',
    effect: '+11.6 pp',
    source: 'Diabetes Obes Metab 24:1553',
  },
  {
    study: 'SURMOUNT-5 (Aronne 2025)',
    design: 'Open-label, active comparator',
    n: '751',
    endpoint: 'Δ body weight, wk 72',
    effect: '−20.2% vs −13.7%',
    source: 'NEJM 392:26',
  },
];

export function LiteraturePage() {
  return (
    <DualPaneWorkspace
      storageKey="literature"
      defaultRatio={0.4}
      leftLabel="Literature agent thread"
      rightLabel="Evidence review table"
      left={
        <Panel
          title="Literature agent"
          actions={<StatusPill tone="validated">12 screened</StatusPill>}
          className={styles.fill}
          flush
        >
          <div className={styles.thread}>
            {THREAD.map((turn, index) => (
              <article key={index} className={styles[turn.role]}>
                <span className={styles.speaker}>{turn.role === 'agent' ? 'Agent' : 'You'}</span>
                <p className={styles.turnBody}>{turn.body}</p>
                {turn.citations && (
                  <div className={styles.citations}>
                    {turn.citations.map((citation) => (
                      <span key={citation} className={styles.citation}>
                        {citation}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
          <div className={styles.composer}>
            <div className={styles.queryChips}>
              {QUERY_CHIPS.map((chip) => (
                <span key={chip} className={styles.queryChip}>
                  {chip}
                </span>
              ))}
            </div>
            <div className={styles.input} aria-hidden="true">
              Ask a follow-up, or refine the query…
            </div>
          </div>
        </Panel>
      }
      right={
        <Panel
          title="Evidence review"
          actions={
            <div className={styles.tableActions}>
              <span className={styles.filter}>n ≥ 200</span>
              <span className={styles.filter}>RCT only</span>
              <span className={styles.count}>8 studies</span>
            </div>
          }
          className={styles.fill}
          flush
        >
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Study</th>
                <th scope="col">Design</th>
                <th scope="col" className={styles.numeric}>
                  n
                </th>
                <th scope="col">Primary endpoint</th>
                <th scope="col" className={styles.numeric}>
                  Effect
                </th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.study}>
                  <th scope="row" className={styles.studyCell}>
                    {row.study}
                  </th>
                  <td>{row.design}</td>
                  <td className={styles.numeric}>{row.n}</td>
                  <td>{row.endpoint}</td>
                  <td className={[styles.numeric, styles.effect].join(' ')}>{row.effect}</td>
                  <td>
                    <span className={styles.sourceLink}>{row.source}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      }
    />
  );
}
