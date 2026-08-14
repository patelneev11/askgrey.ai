import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import styles from './TabPlaceholder.module.css';

interface TabPlaceholderProps {
  title: string;
  /** One line on what the tab will do, so the shell reads as the product, not as lorem ipsum. */
  summary: string;
  /** Stable key for persisting this tab's divider position. */
  paneKey: string;
  rightTitle: string;
}

export function TabPlaceholder({ title, summary, paneKey, rightTitle }: TabPlaceholderProps) {
  return (
    <DualPaneWorkspace
      storageKey={paneKey}
      leftLabel={`${title} assistant`}
      rightLabel={rightTitle}
      left={
        <Panel
          title={title}
          actions={<StatusPill tone="idle">Idle</StatusPill>}
          className={styles.fill}
        >
          <p className={styles.summary}>{summary}</p>
          <div className={styles.composer} aria-hidden="true">
            <span className={styles.composerHint}>Ask the {title.toLowerCase()} agent…</span>
          </div>
        </Panel>
      }
      right={
        <Panel title={rightTitle} className={styles.fill}>
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>Nothing to display yet</p>
            <p className={styles.emptyBody}>
              Results, drafts and visualizations for {title} render in this pane.
            </p>
          </div>
        </Panel>
      }
    />
  );
}
