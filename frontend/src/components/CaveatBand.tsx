import type { ReactNode } from 'react';

import styles from './CaveatBand.module.css';

interface CaveatBandProps {
  /** Short lead, e.g. "Unvalidated prediction". Rendered before the body on the same line. */
  label: string;
  children: ReactNode;
}

/**
 * The standing reliability warning for agent-generated or computationally predicted content.
 *
 * Distinct from `StatusPill tone="idle">Sample data</StatusPill>`, which states where a record
 * came from: this states how far the content can be trusted, and must stay visible even once a
 * surface is wired to a real backend.
 */
export function CaveatBand({ label, children }: CaveatBandProps) {
  return (
    <aside className={styles.band} role="note">
      <span className={styles.mark} aria-hidden="true">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor">
          <path d="M8 2.5 14.5 13.5H1.5L8 2.5Z" strokeWidth="1.3" strokeLinejoin="round" />
          <path d="M8 6.5v3.2" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="8" cy="11.6" r="0.7" fill="currentColor" stroke="none" />
        </svg>
      </span>
      <p className={styles.text}>
        <span className={styles.label}>{label}</span>
        {children}
      </p>
    </aside>
  );
}
