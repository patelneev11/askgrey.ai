import type { ReactNode } from 'react';

import styles from './StatusPill.module.css';

/**
 * Semantic status vocabulary for the whole product. The mapping to accent colour lives here
 * and nowhere else, so a pipeline run always reads acid blue, a compliance or toxicity alert
 * always reads muted amber, and a passed validation checkpoint always reads emerald.
 */
export type StatusTone = 'running' | 'warning' | 'validated' | 'idle';

interface StatusPillProps {
  tone: StatusTone;
  children: ReactNode;
  pulse?: boolean;
}

export function StatusPill({ tone, children, pulse = false }: StatusPillProps) {
  const classes = [styles.pill, styles[tone], pulse ? styles.pulse : ''].filter(Boolean).join(' ');

  return (
    <span className={classes} data-tone={tone}>
      <span className={styles.dot} aria-hidden="true" />
      {children}
    </span>
  );
}
