import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';

import { productUrl } from '@/lib/hosts';

import styles from './marketing.module.css';
import type { ProductTab } from './tabs';
import { PRODUCT_TABS, tabPath } from './tabs';
import { useReveal } from './useReveal';

/**
 * The nine tabs as a strip, with the one being read marked.
 *
 * It repeats on every tab page on purpose: a visitor who lands here from search has not seen
 * the homepage index, and this is the only place that says what else the product does.
 */
function TabRail({ current }: { current: ProductTab }) {
  const activeRef = useRef<HTMLAnchorElement>(null);

  // The strip scrolls sideways on a phone, so a later tab's mark would sit off its right edge
  // and the page would look like it belonged to Literature. On a cold load the pills are still
  // being laid out when the effect runs, and on a rotation they move, so it waits for the fonts
  // and follows the width.
  useEffect(() => {
    let cancelled = false;
    const show = () => {
      if (!cancelled) activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'center' });
    };
    show();
    const frame = requestAnimationFrame(show);
    void document.fonts?.ready.then(show);
    window.addEventListener('resize', show);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', show);
    };
  }, [current.id]);

  return (
    <nav className={styles.tabRail} aria-label="Product">
      {PRODUCT_TABS.map((tab) => {
        const active = tab.id === current.id;
        return (
          <Link
            key={tab.id}
            ref={active ? activeRef : undefined}
            to={tabPath(tab)}
            className={[styles.tabRailLink, active ? styles.tabRailLinkActive : '']
              .filter(Boolean)
              .join(' ')}
            aria-current={active ? 'page' : undefined}
          >
            {tab.name}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * The tab's own take, and the only video on the page.
 *
 * It plays muted on loop like a figure rather than a film: no soundtrack, no narration, and the
 * controls stay available for the one person who wants to scrub back to the moment named above
 * it. Each tab points at its own file, so no two pages show the same recording.
 */
function TabFilm({ tab }: { tab: ProductTab }) {
  const filmRef = useReveal<HTMLElement>();

  return (
    <section className={styles.film} id="film" ref={filmRef}>
      <div className={styles.filmInner}>
        <p className={styles.eyebrow}>{tab.name} in one take</p>
        <h2 className={styles.sectionTitle}>{tab.clip.moment}</h2>
        <div className={styles.filmFrame}>
          <video
            className={styles.filmVideo}
            src={tab.clip.src}
            poster={tab.shot}
            controls
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={tab.clip.label}
          />
        </div>
        <p className={styles.previewCaption}>{tab.clip.label}</p>
      </div>
    </section>
  );
}

export function ProductTabPage({ tab }: { tab: ProductTab }) {
  const shotRef = useReveal<HTMLElement>();
  const stepsRef = useReveal<HTMLElement>();
  const outputsRef = useReveal<HTMLElement>();
  const limitsRef = useReveal<HTMLElement>();
  const index = PRODUCT_TABS.findIndex((candidate) => candidate.id === tab.id);
  const next = PRODUCT_TABS[(index + 1) % PRODUCT_TABS.length];

  return (
    <>
      <TabRail current={tab} />

      <header className={styles.tabHero}>
        <p className={styles.eyebrow}>
          {tab.group} · {tab.name}
        </p>
        <h1 className={styles.tabHeroTitle}>{tab.title}</h1>
        <p className={styles.heroLead}>{tab.body}</p>
        <div className={styles.heroActions}>
          <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
            Open the workspace
          </a>
          <Link className={[styles.cta, styles.ctaSecondary].join(' ')} to="/#product">
            See all nine tabs
          </Link>
        </div>
      </header>

      <figure className={styles.tabShot} ref={shotRef}>
        <div className={styles.tabShotFrame}>
          <img src={tab.shot} alt={tab.alt} />
        </div>
        <figcaption className={styles.previewCaption}>{tab.alt}</figcaption>
      </figure>

      <TabFilm tab={tab} />

      <section className={styles.section} id="how" ref={stepsRef}>
        <p className={styles.eyebrow}>How a run goes</p>
        <h2 className={styles.sectionTitle}>What you hand it, and what comes back.</h2>
        <ol className={styles.steps}>
          {tab.steps.map((step, position) => (
            <li className={styles.step} key={step.title}>
              <span className={styles.stepIndex}>{String(position + 1).padStart(2, '0')}</span>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.cardBody}>{step.detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.section} id="outputs" ref={outputsRef}>
        <p className={styles.eyebrow}>What it leaves behind</p>
        <h2 className={styles.sectionTitle}>Work you can hand to someone else.</h2>
        <dl className={styles.proofs}>
          {tab.outputs.map((output) => (
            <div className={styles.proof} key={output.label}>
              <dt>{output.label}</dt>
              <dd>{output.detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.section} id="limits" ref={limitsRef}>
        <p className={styles.eyebrow}>Where it stops</p>
        <h2 className={styles.sectionTitle}>What {tab.name.toLowerCase()} will not do for you.</h2>
        <ul className={styles.limits}>
          {tab.limits.map((limit) => (
            <li className={styles.limit} key={limit}>
              {limit}
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.closing}>
        <div className={styles.closingPanel}>
          <h2 className={styles.closingTitle}>{next.title}</h2>
          <p className={styles.closingLead}>{next.summary}</p>
          <Link className={[styles.cta, styles.ctaSecondary].join(' ')} to={tabPath(next)}>
            {next.name}
          </Link>
        </div>
      </section>
    </>
  );
}
