import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import styles from './ProtocolPage.module.css';

interface Step {
  title: string;
  duration: string;
  state: 'done' | 'active' | 'todo';
}

const OUTLINE: Step[] = [
  { title: 'Cell thaw & seeding', duration: '45 min', state: 'done' },
  { title: 'Compound dilution series', duration: '30 min', state: 'done' },
  { title: 'Treatment & incubation', duration: '24 h', state: 'active' },
  { title: 'Viability readout (CTG)', duration: '1 h', state: 'todo' },
  { title: 'Plate normalization & QC', duration: '20 min', state: 'todo' },
  { title: 'ELN export', duration: '5 min', state: 'todo' },
];

const REAGENTS = [
  { reagent: 'DMEM, high glucose', stock: '—', final: '—', volume: '450 mL' },
  {
    reagent: 'Fetal bovine serum',
    stock: '100%',
    final: '10%',
    volume: '50 mL',
  },
  {
    reagent: 'AG-0412 in DMSO',
    stock: '10 mM',
    final: '10 µM',
    volume: '500 µL',
  },
  {
    reagent: 'Penicillin/streptomycin',
    stock: '100×',
    final: '1×',
    volume: '5 mL',
  },
];

export function ProtocolPage() {
  return (
    <DualPaneWorkspace
      storageKey="protocol"
      defaultRatio={0.28}
      leftLabel="Protocol outline"
      rightLabel="Protocol draft"
      left={
        <Panel
          title="Outline"
          actions={<span className={styles.totalTime}>26 h 40 m</span>}
          className={styles.fill}
        >
          <ol className={styles.outline}>
            {OUTLINE.map((step, index) => (
              <li key={step.title} className={styles[step.state]}>
                <span className={styles.marker} aria-hidden="true">
                  {index + 1}
                </span>
                <span className={styles.stepBody}>
                  <span className={styles.stepTitle}>{step.title}</span>
                  <span className={styles.stepDuration}>{step.duration}</span>
                </span>
              </li>
            ))}
          </ol>
          <div className={styles.controls}>
            <h3 className={styles.controlsTitle}>Controls required</h3>
            <ul className={styles.controlList}>
              <li>Vehicle control (0.1% DMSO)</li>
              <li>Positive control (staurosporine, 1 µM)</li>
              <li>Media-only blank, n = 6 wells</li>
            </ul>
          </div>
        </Panel>
      }
      right={
        <Panel
          title="Cytotoxicity screen — AG-0412"
          actions={
            <div className={styles.docActions}>
              <StatusPill tone="validated">Controls validated</StatusPill>
              <span className={styles.version}>v4 · draft</span>
            </div>
          }
          className={styles.fill}
          flush
        >
          <article className={styles.document}>
            <header className={styles.docHeader}>
              <p className={styles.eyebrow}>Laboratory protocol</p>
              <h1 className={styles.docTitle}>
                48-hour cytotoxicity screen of AG-0412 in HepG2 cells
              </h1>
              <p className={styles.docMeta}>
                Drafted by the protocol agent from the STEP analog series brief · last edited 2
                hours ago
              </p>
            </header>

            <section>
              <h2 className={styles.docSection}>1. Materials</h2>
              <table className={styles.reagents}>
                <thead>
                  <tr>
                    <th scope="col">Reagent</th>
                    <th scope="col">Stock</th>
                    <th scope="col">Final</th>
                    <th scope="col">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {REAGENTS.map((row) => (
                    <tr key={row.reagent}>
                      <th scope="row">{row.reagent}</th>
                      <td className={styles.mono}>{row.stock}</td>
                      <td className={styles.mono}>{row.final}</td>
                      <td className={styles.mono}>{row.volume}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section>
              <h2 className={styles.docSection}>2. Treatment &amp; incubation</h2>
              <p className={styles.docBody}>
                Seed HepG2 cells at 8 × 10³ cells/well in 96-well plates and allow to adhere
                overnight at 37 °C, 5% CO₂. Prepare an eight-point, threefold dilution series of
                AG-0412 starting at{' '}
                <span className={styles.calc} title="10 mM stock diluted 1:1000 in complete media">
                  10 µM
                </span>
                , keeping the vehicle at{' '}
                <span className={styles.calc} title="0.1% v/v DMSO across every well">
                  0.1% DMSO
                </span>{' '}
                across all wells. Treat in triplicate and return plates to the incubator for 48 h.
              </p>
              <aside className={styles.note}>
                Agent note: the vehicle concentration is held constant across the series so the
                dose–response curve is not confounded by solvent toxicity.
              </aside>
            </section>

            <section>
              <h2 className={styles.docSection}>3. Readout</h2>
              <p className={styles.docBody}>
                Equilibrate CellTiter-Glo to room temperature, add 100 µL per well, shake for 2 min
                and record luminescence after a 10-minute stabilization. Normalize each plate to its
                vehicle control and fit a four-parameter logistic curve to derive IC₅₀.
              </p>
            </section>
          </article>
        </Panel>
      }
    />
  );
}
