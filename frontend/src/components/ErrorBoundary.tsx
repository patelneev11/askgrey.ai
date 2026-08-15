import { Component, type ErrorInfo, type ReactNode } from 'react';

import { logger } from '@/lib/observability';

import { Button } from './Button';
import styles from './ErrorBoundary.module.css';

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

/**
 * Last resort for a render-time crash.
 *
 * Without this React unmounts the tree and the user is left on a blank page with no way to
 * report what happened; here they get an explanation and a reload, and the failure is logged
 * (and sent to Sentry) whether or not they tell anyone.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logger.error('ui.crash', error, { component_stack: info.componentStack?.slice(0, 500) ?? '' });
  }

  render(): ReactNode {
    if (!this.state.failed) {
      return this.props.children;
    }
    return (
      <div className={styles.shell} role="alert">
        <div className={styles.card}>
          <h1 className={styles.title}>Something broke in the interface</h1>
          <p className={styles.body}>
            The error has been recorded. Reloading usually recovers the session; unsaved papers
            and generated columns in this workspace will be lost.
          </p>
          <Button onClick={() => window.location.reload()}>Reload AskGrey</Button>
        </div>
      </div>
    );
  }
}
