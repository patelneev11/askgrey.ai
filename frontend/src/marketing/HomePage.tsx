import { productUrl } from '@/lib/hosts';

import heroShot from './screens/literature.webp';
import styles from './marketing.module.css';
import { Section } from './Section';
import type { ProductTab } from './tabs';
import { PRODUCT_TABS } from './tabs';
import { useReveal } from './useReveal';

const SOURCES = [
  'PubMed',
  'PubChem',
  'ClinicalTrials.gov',
  'grants.gov',
  'SBIR.gov',
  'USPTO',
  'your own PDFs',
];

/** Counts of what is built — no usage, customer or performance number appears on this page. */
const FIGURES = [
  { value: '9', label: 'tabs, each a job a preclinical team already has' },
  {
    value: '6',
    label: 'public databases queried directly, plus the PDFs you upload',
  },
  {
    value: '16',
    label: 'typed, read-only tools the assistant may call — and nothing else',
  },
  { value: '0', label: 'model API keys for you to buy, rotate or expose' },
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

/** The product's own Literature tab, captured against the repository's fixture papers. */
function InterfacePreview() {
  const ref = useReveal<HTMLElement>();

  return (
    <figure className={styles.preview} ref={ref}>
      <div className={styles.previewFrame}>
        <img className={styles.previewShot} src={heroShot} alt={PRODUCT_TABS[0].alt} />
      </div>
      <figcaption className={styles.previewCaption}>
        The Literature tab, running. Every extracted value opens the page it was read from.
      </figcaption>
    </figure>
  );
}

/** A silent screen capture of one run through the product, looped like a diagram. */
function DemoFilm() {
  const ref = useReveal<HTMLElement>();

  return (
    <section className={styles.film} id="watch" ref={ref}>
      <div className={styles.filmInner}>
        <p className={styles.eyebrow}>Thirty seconds</p>
        <h2 className={styles.sectionTitle}>Watch a question become a cited table.</h2>
        <p className={styles.sectionLead}>
          One unedited run: two papers uploaded, the columns asked for in plain English, then a
          value clicked to open the sentence it was read from.
        </p>
        <div className={styles.filmFrame}>
          <video
            className={styles.filmVideo}
            src="/demo/askgrey-literature.mp4"
            poster={heroShot}
            controls
            muted
            loop
            autoPlay
            playsInline
            preload="metadata"
            aria-label="Screen recording of AskGrey extracting cited values from two uploaded papers"
          />
        </div>
      </div>
    </section>
  );
}

/** One tab, told once: what it is for, then the tab itself. */
function TabHighlight({ tab, index }: { tab: ProductTab; index: number }) {
  const ref = useReveal<HTMLElement>();

  const className = [styles.highlight, index % 2 === 1 ? styles.highlightFlip : '']
    .filter(Boolean)
    .join(' ');

  return (
    <section className={className} id={tab.id} ref={ref}>
      <div className={styles.highlightText}>
        <p className={styles.eyebrow}>
          {String(index + 1).padStart(2, '0')} · {tab.name}
        </p>
        <h3 className={styles.highlightTitle}>{tab.title}</h3>
        <p className={styles.cardBody}>{tab.body}</p>
        <ul className={styles.highlightPoints}>
          {tab.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      </div>
      <figure className={styles.highlightShot}>
        <img src={tab.shot} alt={tab.alt} loading="lazy" decoding="async" />
      </figure>
    </section>
  );
}

function Figures() {
  const ref = useReveal<HTMLElement>();

  return (
    <section className={styles.figures} ref={ref}>
      <div className={styles.figuresInner}>
        {FIGURES.map((figure) => (
          <div key={figure.label} className={styles.figure}>
            <span className={styles.figureValue}>{figure.value}</span>
            <span className={styles.figureLabel}>{figure.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function HomePage() {
  return (
    <>
      <header className={styles.hero}>
        <div className={styles.heroGrid}>
          <h1 className={styles.heroTitle}>
            Biomedical answers you can <span className={styles.heroAccent}>check</span>.
          </h1>
          <div>
            <p className={styles.heroLead}>
              AskGrey is a research workspace for preclinical teams: it searches the literature,
              screens compounds, drafts protocols and IND sections, and finds funding — and every
              number it gives you links back to the paper and page it was read from. When the
              sources cannot answer, it says so.
            </p>
            <div className={styles.heroActions}>
              <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
                Open the workspace
              </a>
              <a className={[styles.cta, styles.ctaSecondary].join(' ')} href="#how-it-works">
                See how it works
              </a>
            </div>
            <p className={styles.heroNote}>
              Built for preclinical biotech and academic labs. No model API key of your own
              required.
            </p>
          </div>
        </div>
      </header>

      <InterfacePreview />


      <div className={styles.sourcesBand}>
        <div className={styles.sourcesInner}>
          <p className={styles.sourcesLabel}>Reads from</p>
          <ul className={styles.sources}>
            {SOURCES.map((source) => (
              <li key={source} className={styles.source}>
                {source}
              </li>
            ))}
          </ul>
        </div>
      </div>

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

        <DemoFilm />

        <Figures />

        <Section
          id="product"
          eyebrow="What is inside"
          title="Nine tabs, one evidence trail."
          lead="Each tab is a job a preclinical team already has, and each writes to the same audit trail and the same shared workspace."
        >
          <ul className={styles.tabIndex}>
            {PRODUCT_TABS.map((tab) => (
              <li key={tab.id}>
                <a className={styles.tabIndexLink} href={`#${tab.id}`}>
                  {tab.name}
                </a>
              </li>
            ))}
          </ul>
        </Section>

        {PRODUCT_TABS.map((tab, index) => (
          <TabHighlight key={tab.id} tab={tab} index={index} />
        ))}

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
            <h2 className={styles.closingTitle}>Bring a question you are stuck on.</h2>
            <p className={styles.closingLead}>
              Create an account and run it against the literature. We are taking design partners in
              preclinical discovery.
            </p>
            <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
              Open the workspace
            </a>
          </div>
        </section>
      </main>
    </>
  );
}
