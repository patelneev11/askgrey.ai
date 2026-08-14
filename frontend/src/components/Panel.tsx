import type { ReactNode } from 'react';

import styles from './Panel.module.css';

interface PanelProps {
  title?: ReactNode;
  /** Rendered on the right of the panel header — status pills, actions, view switches. */
  actions?: ReactNode;
  /** Removes body padding, for panels hosting tables or editors that own their own gutters. */
  flush?: boolean;
  className?: string;
  children: ReactNode;
}

export function Panel({ title, actions, flush = false, className, children }: PanelProps) {
  return (
    <section className={[styles.panel, className].filter(Boolean).join(' ')}>
      {(title || actions) && (
        <header className={styles.header}>
          {title && <h2 className={styles.title}>{title}</h2>}
          {actions && <div className={styles.actions}>{actions}</div>}
        </header>
      )}
      <div className={flush ? styles.bodyFlush : styles.body}>{children}</div>
    </section>
  );
}
