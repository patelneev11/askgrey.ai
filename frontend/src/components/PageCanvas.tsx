import type { ReactNode } from 'react';

import styles from './PageCanvas.module.css';

interface PageCanvasProps {
  title: string;
  /** One line of orientation under the title. */
  description?: string;
  /** Buttons or filters aligned to the right of the title. */
  actions?: ReactNode;
  /** Constrains the body to a readable measure, for settings and profile forms. */
  narrow?: boolean;
  children: ReactNode;
}

/**
 * Scrolling single-column page frame. Used by the administrative destinations, which are
 * documents to read rather than workspaces to work in, so they deliberately skip the split.
 */
export function PageCanvas({ title, description, actions, narrow, children }: PageCanvasProps) {
  return (
    <div className={styles.canvas}>
      <div className={[styles.inner, narrow ? styles.narrow : ''].filter(Boolean).join(' ')}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>{title}</h1>
            {description && <p className={styles.description}>{description}</p>}
          </div>
          {actions && <div className={styles.actions}>{actions}</div>}
        </header>
        {children}
      </div>
    </div>
  );
}
