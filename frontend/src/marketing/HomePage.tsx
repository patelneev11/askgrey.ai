import type { IconName } from '@/components/icons';
import { Icon } from '@/components/icons';
import { productUrl } from '@/lib/hosts';

import styles from './marketing.module.css';
import { Section } from './Section';
import { useSeo } from './useSeo';

const SOURCES = [
  'PubMed',
  'PubChem',
  'ClinicalTrials.gov',
  'grants.gov',
  'SBIR.gov',
  'USPTO',
  'your own PDFs',
];

const STEPS = [
  {
    title: 'Ask in plain English',
    body: 'Describe the question the way you would to a colleague — a target, a compound, a protocol you need, a funding gap.',
  },
  {
    title: 'It fetches from named sources',
    body: 'Typed, read-only tools query public biomedical databases and the papers you have uploaded. Nothing is invented to fill a gap.',
  },
  {
    title: 'Every claim carries its source',
    body: 'Extracted values link to the paper and page they came from. Predicted values are labelled as predictions, and an unanswerable question is answered with "I do not know".',
  },
];

const CAPABILITIES: { icon: IconName; title: string; body: string }[] = [
  {
    icon: 'assistant',
    title: 'Assistant',
    body: 'A biomedical research chat with read-only tools over every other tab. Off-topic questions are refused before a model is ever called, so the credits go to research.',
  },
  {
    icon: 'literature',
    title: 'Literature',
    body: 'Search PubMed, upload PDFs, and pull a goal-driven table of extracted values out of them — each cell clicking through to the sentence and page it was read from. Export to Excel or CSV with a linked sources sheet.',
  },
  {
    icon: 'screening',
    title: 'Screening',
    body: 'Descriptors, rule sets and QSAR-based ADMET estimates for a SMILES string, opening with what needs reviewing: fired liabilities, borderline calls, rule violations. Estimates, not a safety assessment.',
  },
  {
    icon: 'protocol',
    title: 'Protocol',
    body: 'Draft a protocol with controls and a master-mix calculator, keep its version history, and export a notebook bundle any ELN can import.',
  },
  {
    icon: 'regulatory',
    title: 'Regulatory',
    body: 'Preclinical package and IND section drafting with a guideline checker that says which requirement each statement answers, and which are still unaddressed.',
  },
  {
    icon: 'grants',
    title: 'Grants',
    body: 'Find NIH/SBIR opportunities matched to your work, check eligibility against editable federal rules, build an SF-424 (R&R) budget, and get a mock review-board critique before you submit.',
  },
  {
    icon: 'workspace',
    title: 'Workspace',
    body: 'Share saved literature, protocols and screens with your team through workspaces with seats, roles and single-use invitations.',
  },
  {
    icon: 'audit',
    title: 'Audit',
    body: 'Every document, model call, invitation and export is written to an append-only trail you can read, with outcomes — including refusals and failures.',
  },
  {
    icon: 'settings',
    title: 'Settings',
    body: 'Retention windows, spend and rate limits, storage and encryption state, read from the account itself rather than hard-coded.',
  },
];

const PROOFS = [
  {
    title: 'It refuses rather than guesses',
    body: 'A question the sources cannot ground comes back unanswered and labelled, not filled in. Dangerous requests are refused deterministically before any model call.',
  },
  {
    title: 'Documents are encrypted per document',
    body: 'Uploaded papers are sealed with a KMS-minted data key of their own and stored in your own S3 bucket, with a retention window you set.',
  },
  {
    title: 'The model never sees your files',
    body: 'Attachments are referenced by id; raw bytes and filesystem paths are never sent to the model provider.',
  },
  {
    title: 'Spend is capped, per account',
    body: 'Per-account rate limits and a daily call and cost budget mean one user cannot drain the workspace.',
  },
];

const LIMITS = [
  {
    title: 'No live ELN sync yet',
    body: 'Protocols export as a vendor-neutral notebook bundle. A direct Benchling or LabArchives connection needs your tenant and is not built.',
  },
  {
    title: 'Not for PHI',
    body: 'Do not put patient data in it. That would need a BAA with our model provider, which we do not have.',
  },
  {
    title: 'No third-party penetration test',
    body: 'The security work is real and documented, but it has not been audited by an outside firm.',
  },
  {
    title: 'Predictions are predictions',
    body: 'ADMET and liability estimates are models over public data, marked as such. They are not a toxicology or safety assessment.',
  },
];

export function HomePage() {
  useSeo({
    title: 'AskGrey — evidence-backed biomedical research workspace',
    description:
      'AskGrey searches the literature, screens compounds, drafts protocols and IND sections, and finds grants — with every claim linked to the paper and page it came from.',
    path: '/',
  });

  return (
    <>
      <header className={styles.hero}>
        <h1 className={styles.heroTitle}>
          Biomedical answers you can <span className={styles.heroAccent}>check</span>.
        </h1>
        <p className={styles.heroLead}>
          AskGrey is a research workspace for preclinical teams: it searches the literature,
          screens compounds, drafts protocols and IND sections, and finds funding — and every
          number it gives you links back to the paper and page it was read from. When the sources
          cannot answer, it says so.
        </p>
        <div className={styles.heroActions}>
          <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
            Open the workspace
          </a>
          <a className={[styles.cta, styles.ctaSecondary].join(' ')} href="#how-it-works">
            See how it works
          </a>
        </div>
        <ul className={styles.sources}>
          {SOURCES.map((source) => (
            <li key={source} className={styles.source}>
              {source}
            </li>
          ))}
        </ul>
        <p className={styles.heroNote}>
          Built for preclinical biotech and academic labs. No model API key of your own required.
        </p>
      </header>

      <main className={styles.main}>
        <Section
          id="how-it-works"
          eyebrow="How it works"
          title="Ask, fetch, cite. In that order."
          lead="The order matters: the answer is assembled from sources that were actually retrieved, so there is always something to click through to."
        >
          <ol className={styles.steps}>
            {STEPS.map((step, index) => (
              <li key={step.title} className={styles.step}>
                <span className={styles.stepIndex}>{String(index + 1).padStart(2, '0')}</span>
                <h3 className={styles.cardTitle}>{step.title}</h3>
                <p className={styles.cardBody}>{step.body}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section
          id="product"
          eyebrow="What is inside"
          title="Nine tabs, one evidence trail."
          lead="Each tab is a job a preclinical team actually has, and each writes to the same audit trail and the same shared workspace."
        >
          <ul className={styles.cards}>
            {CAPABILITIES.map((capability) => (
              <li key={capability.title} className={styles.card}>
                <span className={styles.cardIcon} aria-hidden="true">
                  <Icon name={capability.icon} size={18} />
                </span>
                <h3 className={styles.cardTitle}>{capability.title}</h3>
                <p className={styles.cardBody}>{capability.body}</p>
              </li>
            ))}
          </ul>
        </Section>

        <Section
          id="trust"
          eyebrow="Why trust it"
          title="A research tool is only worth the citation behind it."
          lead="The product is built to be checkable by a reviewer who assumes the model is wrong."
        >
          <dl className={styles.proofs}>
            {PROOFS.map((proof) => (
              <div key={proof.title} className={styles.proof}>
                <dt>{proof.title}</dt>
                <dd>{proof.body}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section
          id="limits"
          eyebrow="Straight answers"
          title="What AskGrey does not do."
          lead="Said here rather than discovered after you have signed up."
        >
          <ul className={styles.limits}>
            {LIMITS.map((limit) => (
              <li key={limit.title} className={styles.limit}>
                <span className={styles.limitTitle}>{limit.title}</span>
                {limit.body}
              </li>
            ))}
          </ul>
        </Section>

        <section className={styles.closing} id="start">
          <div className={styles.closingPanel}>
            <div>
              <h2 className={styles.sectionTitle}>Bring a question you are stuck on.</h2>
              <p className={styles.sectionLead}>
                Create an account and run it against the literature. We are taking design partners
                in preclinical discovery.
              </p>
            </div>
            <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
              Open the workspace
            </a>
          </div>
        </section>
      </main>
    </>
  );
}
