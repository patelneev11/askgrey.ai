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
  // and the page would look like it belonged to Literature.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'center' });
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

export function ProductTabPage({ tab }: { tab: ProductTab }) {
  const shotRef = useReveal<HTMLElement>();
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

      <section className={styles.section}>
        <p className={styles.eyebrow}>What you get</p>
        <ul className={styles.highlightPoints}>
          {tab.points.map((point) => (
            <li key={point}>{point}</li>
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
