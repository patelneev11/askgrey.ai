import type { ReactNode } from 'react';

import styles from './EmptyState.module.css';

interface EmptyStateProps {
  title: string;
  children: ReactNode;
  /** Optional next step, e.g. a button that focuses the input the user needs. */
  action?: ReactNode;
}

/**
 * A pane with nothing in it yet still owes the user an explanation of what would fill it and
 * how to make that happen. Never render a bare blank surface.
 */
export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <p className={styles.title}>{title}</p>
      <div className={styles.body}>{children}</div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
