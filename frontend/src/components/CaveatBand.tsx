import type { ReactNode } from 'react';

import styles from './CaveatBand.module.css';

interface CaveatBandProps {
  /** Short lead, e.g. "Unvalidated". Rendered before the body on the same line. */
  label: string;
  children: ReactNode;
}

/**
 * The reliability note for extracted values and computational predictions.
 *
 * It used to be an amber warning panel with a hazard triangle, repeated on every tab. That is how
 * a caveat stops being read: the full statement of these limits now lives in the terms of
 * agreement each account accepts, and what stays here is one small line of text beside the two
 * outputs that would otherwise be read as measurements — an extracted value and a prediction.
 *
 * Distinct from `StatusPill tone="idle">Sample data</StatusPill>`, which states where a record
 * came from: this states how far the content can be trusted, and must stay visible even once a
 * surface is wired to a real backend.
 */
export function CaveatBand({ label, children }: CaveatBandProps) {
  return (
    <p className={styles.band} role="note">
      <span className={styles.label}>{label}</span>
      {children}
      {/* A plain anchor, not a router link: it opens in its own tab, and this note renders on
          surfaces that tests and future embeds may mount outside a router. */}
      <a className={styles.link} href="/terms" target="_blank" rel="noreferrer">
        Terms
      </a>
    </p>
  );
}
