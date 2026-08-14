import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import styles from './RegulatoryPage.module.css';

interface Module {
  id: string;
  title: string;
  completeness: number;
  sections: { title: string; state: 'complete' | 'review' | 'empty' }[];
}

const MODULES: Module[] = [
  {
    id: 'M1',
    title: 'Administrative',
    completeness: 1,
    sections: [
      { title: '1.1 Forms 1571 / 1572', state: 'complete' },
      { title: '1.3 Investigator brochure', state: 'complete' },
    ],
  },
  {
    id: 'M2',
    title: 'CTD summaries',
    completeness: 0.66,
    sections: [
      { title: '2.4 Nonclinical overview', state: 'complete' },
      { title: '2.6 Written summaries', state: 'review' },
      { title: '2.7 Clinical summary', state: 'empty' },
    ],
  },
  {
    id: 'M3',
    title: 'Quality (CMC)',
    completeness: 0.4,
    sections: [
      { title: '3.2.S Drug substance', state: 'review' },
      { title: '3.2.P Drug product', state: 'empty' },
    ],
  },
  {
    id: 'M4',
    title: 'Nonclinical study reports',
    completeness: 0.85,
    sections: [
      { title: '4.2.3 Toxicology', state: 'complete' },
      { title: '4.2.2 Pharmacokinetics', state: 'review' },
    ],
  },
];

const DISCREPANCIES = [
  {
    anchor: '2.6.6',
    severity: 'High',
    body: 'NOAEL stated as 25 mg/kg/day here but 30 mg/kg/day in the 4.2.3 toxicology report.',
  },
  {
    anchor: '2.6.4',
    severity: 'Medium',
    body: 'Species justification does not cite the receptor-homology data required by ICH M3(R2) §3.',
  },
];

function CompletenessRing({ value }: { value: number }) {
  const circumference = 2 * Math.PI * 9;

  return (
    <svg className={styles.ring} viewBox="0 0 24 24" aria-hidden="true">
      <circle className={styles.ringTrack} cx="12" cy="12" r="9" />
      <circle
        className={styles.ringFill}
        cx="12"
        cy="12"
        r="9"
        strokeDasharray={`${circumference * value} ${circumference}`}
      />
    </svg>
  );
}

export function RegulatoryPage() {
  return (
    <DualPaneWorkspace
      storageKey="regulatory"
      defaultRatio={0.3}
      leftLabel="Submission structure"
      rightLabel="Submission draft"
      left={
        <Panel
          title="IND · eCTD structure"
          actions={
            <div className={styles.docActions}>
              <StatusPill tone="idle">Sample data</StatusPill>
              <span className={styles.overall}>68% complete</span>
            </div>
          }
          className={styles.fill}
        >
          <ul className={styles.tree}>
            {MODULES.map((module) => (
              <li key={module.id} className={styles.module}>
                <div className={styles.moduleHead}>
                  <CompletenessRing value={module.completeness} />
                  <span className={styles.moduleId}>{module.id}</span>
                  <span className={styles.moduleTitle}>{module.title}</span>
                </div>
                <ul className={styles.sections}>
                  {module.sections.map((section) => (
                    <li key={section.title} className={styles[section.state]}>
                      <span className={styles.sectionDot} aria-hidden="true" />
                      {section.title}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Panel>
      }
      right={
        <Panel
          title="2.6 Nonclinical written summary"
          actions={
            <div className={styles.docActions}>
              <StatusPill tone="warning">2 discrepancies</StatusPill>
              <span className={styles.guideline}>FDA · ICH M3(R2)</span>
            </div>
          }
          className={styles.fill}
          flush
        >
          <div className={styles.docLayout}>
            <article className={styles.document}>
              <h1 className={styles.docTitle}>2.6.6 Toxicology written summary</h1>
              <p className={styles.docBody}>
                Repeat-dose toxicity of AG-0412 was evaluated in Sprague-Dawley rats and beagle dogs
                over 28 days at 5, 15 and 25 mg/kg/day. Systemic exposure increased approximately
                dose-proportionally with no evidence of accumulation on day 28.
              </p>
              <p className={[styles.docBody, styles.flagged].join(' ')}>
                The no-observed-adverse-effect level (NOAEL) was determined to be 25 mg/kg/day in
                both species, corresponding to a 12-fold exposure margin over the proposed starting
                clinical dose.
              </p>
              <p className={styles.docBody}>
                Genotoxicity was assessed in a standard battery comprising the bacterial reverse
                mutation assay, an in vitro micronucleus assay in human lymphocytes, and an in vivo
                rat bone-marrow micronucleus assay. All results were negative.
              </p>
              <p className={[styles.docBody, styles.flaggedMedium].join(' ')}>
                The rat and dog were selected as the pharmacologically relevant species for
                toxicology assessment.
              </p>
            </article>

            <aside className={styles.margin}>
              <h2 className={styles.marginTitle}>Discrepancy audit</h2>
              {DISCREPANCIES.map((item) => (
                <div key={item.anchor} className={styles.discrepancy}>
                  <span className={styles.discrepancyHead}>
                    <span className={styles.anchor}>{item.anchor}</span>
                    <span className={styles.severity}>{item.severity}</span>
                  </span>
                  <p className={styles.discrepancyBody}>{item.body}</p>
                </div>
              ))}
              <div className={styles.checklist}>
                <h2 className={styles.marginTitle}>Guideline alignment</h2>
                <ul>
                  <li className={styles.pass}>ICH M3(R2) — exposure margins</li>
                  <li className={styles.pass}>ICH S2(R1) — genotoxicity battery</li>
                  <li className={styles.pending}>ICH S7A — safety pharmacology core battery</li>
                </ul>
              </div>
            </aside>
          </div>
        </Panel>
      }
    />
  );
}
