import { Meter } from '@/components/Meter';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import styles from './ScreeningPage.module.css';

interface Candidate {
  id: string;
  name: string;
  smiles: string;
  affinity: string;
  selected?: boolean;
  flagged?: boolean;
}

const QUEUE: Candidate[] = [
  {
    id: 'AG-0412',
    name: 'Analog 12 — pyrazole core',
    smiles: 'CC1=NN(C(=O)C1)c1ccc(Cl)cc1',
    affinity: '8.4',
    selected: true,
  },
  {
    id: 'AG-0417',
    name: 'Analog 17 — fluorinated',
    smiles: 'FC(F)Oc1ccc(cc1)C1=NNC(=O)C1',
    affinity: '7.9',
  },
  {
    id: 'AG-0421',
    name: 'Analog 21 — extended linker',
    smiles: 'O=C(NCCN1CCOCC1)c1ccc(cc1)C#N',
    affinity: '7.1',
    flagged: true,
  },
  {
    id: 'AG-0430',
    name: 'Analog 30 — methylated',
    smiles: 'COc1ccc2[nH]cc(CCN)c2c1',
    affinity: '6.4',
  },
];

const LIPINSKI = [
  { label: 'MW', value: '341.8', limit: '≤ 500', pass: true },
  { label: 'cLogP', value: '3.62', limit: '≤ 5', pass: true },
  { label: 'HBD', value: '1', limit: '≤ 5', pass: true },
  { label: 'HBA', value: '4', limit: '≤ 10', pass: true },
  { label: 'TPSA', value: '68.4 Å²', limit: '≤ 140', pass: true },
  { label: 'Rot. bonds', value: '11', limit: '≤ 10', pass: false },
];

const ADMET = [
  {
    label: 'Caco-2 permeability',
    value: '−4.9 log cm/s',
    fraction: 0.72,
    tone: 'success' as const,
  },
  {
    label: 'Plasma protein binding',
    value: '94.1%',
    fraction: 0.94,
    tone: 'warning' as const,
  },
  {
    label: 'CYP3A4 inhibition',
    value: '0.31 probability',
    fraction: 0.31,
    tone: 'success' as const,
  },
  {
    label: 'hERG liability',
    value: '0.58 probability',
    fraction: 0.58,
    tone: 'warning' as const,
  },
  {
    label: 'Oral bioavailability',
    value: '61%',
    fraction: 0.61,
    tone: 'pipeline' as const,
  },
];

const FLAGS = [
  {
    title: 'hERG channel binding above screening threshold',
    body: 'Predicted 0.58 vs 0.40 internal cut-off. Recommend a patch-clamp assay before the series advances.',
  },
  {
    title: 'Rotatable bonds exceed Veber criterion',
    body: '11 rotatable bonds may depress oral bioavailability; the extended linker in AG-0421 is the likely cause.',
  },
];

export function ScreeningPage() {
  return (
    <DualPaneWorkspace
      storageKey="screening"
      defaultRatio={0.32}
      leftLabel="Compound queue"
      rightLabel="Compound profile"
      left={
        <Panel
          title="Screening queue"
          actions={
            <StatusPill tone="running" pulse>
              Profiling
            </StatusPill>
          }
          className={styles.fill}
          flush
        >
          <ul className={styles.queue}>
            {QUEUE.map((candidate) => (
              <li key={candidate.id}>
                <button
                  type="button"
                  className={[styles.card, candidate.selected ? styles.cardSelected : '']
                    .filter(Boolean)
                    .join(' ')}
                  aria-current={candidate.selected ? 'true' : undefined}
                >
                  <span className={styles.cardHead}>
                    <span className={styles.cardId}>{candidate.id}</span>
                    {candidate.flagged ? (
                      <StatusPill tone="warning">Flagged</StatusPill>
                    ) : (
                      <span className={styles.affinity}>pKi {candidate.affinity}</span>
                    )}
                  </span>
                  <span className={styles.cardName}>{candidate.name}</span>
                  <code className={styles.smiles}>{candidate.smiles}</code>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      }
      right={
        <Panel
          title="AG-0412 — profile"
          actions={<StatusPill tone="warning">1 liability</StatusPill>}
          className={styles.fill}
        >
          <div className={styles.profile}>
            <section className={styles.identity}>
              <div className={styles.structure} aria-hidden="true">
                <span className={styles.structureHint}>2D structure</span>
              </div>
              <dl className={styles.identityFacts}>
                <div>
                  <dt>Series</dt>
                  <dd>Pyrazolone, gen 4</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>GLP-1R allosteric site</dd>
                </div>
                <div>
                  <dt>Predicted pKi</dt>
                  <dd className={styles.strong}>8.4</dd>
                </div>
                <div>
                  <dt>Patent status</dt>
                  <dd>No blocking claim found</dd>
                </div>
              </dl>
            </section>

            <section>
              <h3 className={styles.sectionTitle}>Physicochemical (Lipinski / Veber)</h3>
              <div className={styles.propertyGrid}>
                {LIPINSKI.map((property) => (
                  <div
                    key={property.label}
                    className={[styles.property, property.pass ? '' : styles.propertyFail]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <span className={styles.propertyLabel}>{property.label}</span>
                    <span className={styles.propertyValue}>{property.value}</span>
                    <span className={styles.propertyLimit}>{property.limit}</span>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <h3 className={styles.sectionTitle}>ADMET prediction</h3>
              <div className={styles.meters}>
                {ADMET.map((prediction) => (
                  <Meter key={prediction.label} {...prediction} />
                ))}
              </div>
            </section>

            <section>
              <h3 className={styles.sectionTitle}>Toxicity &amp; liability flags</h3>
              <ul className={styles.flags}>
                {FLAGS.map((flag) => (
                  <li key={flag.title} className={styles.flag}>
                    <span className={styles.flagTitle}>{flag.title}</span>
                    <span className={styles.flagBody}>{flag.body}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </Panel>
      }
    />
  );
}
