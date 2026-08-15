import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

import { Button } from '@/components/Button';
import { useOnboarding } from '@/lib/onboarding-context';
import { TAB_INTROS } from '@/lib/tab-intros';

import styles from './TabIntro.module.css';

/**
 * The first time a user lands on a tab, say what the tab is for and — where the tab produces
 * model output — put its reliability caveat in front of them as something to accept rather than
 * a band in the margin. The standing `CaveatBand` on the page stays either way; this only
 * governs the first encounter.
 */
export function TabIntroHost() {
  const { pathname } = useLocation();
  const { tour, hasAcknowledged, acknowledge } = useOnboarding();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const intro = TAB_INTROS.find((entry) => entry.path === pathname);
  // Never stack on the first-run tour: the tab notice waits until the tour is done or skipped.
  const open = intro !== undefined && tour !== 'unseen' && !hasAcknowledged(intro.id);

  useEffect(() => {
    if (open) headingRef.current?.focus();
  }, [open, intro?.id]);

  if (!intro || !open) return null;

  return (
    <section
      className={styles.notice}
      role="dialog"
      aria-labelledby="tab-intro-title"
      aria-describedby="tab-intro-body"
    >
      <h2 className={styles.title} id="tab-intro-title" tabIndex={-1} ref={headingRef}>
        {intro.title}
      </h2>
      <div className={styles.body} id="tab-intro-body">
        {intro.body.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
      {intro.caveat && <p className={styles.caveat}>{intro.caveat}</p>}
      <div className={styles.actions}>
        <Button variant="primary" size="sm" onClick={() => acknowledge(intro.id)}>
          {intro.caveat ? 'I understand' : 'Got it'}
        </Button>
      </div>
    </section>
  );
}
