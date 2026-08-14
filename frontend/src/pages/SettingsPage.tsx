import { PageCanvas } from '@/components/PageCanvas';
import { StatusPill } from '@/components/StatusPill';

import styles from './SettingsPage.module.css';

interface Row {
  label: string;
  help: string;
  control: 'toggle-on' | 'toggle-off' | 'select' | 'text';
  value?: string;
}

interface Group {
  title: string;
  summary: string;
  rows: Row[];
}

const GROUPS: Group[] = [
  {
    title: 'Authentication',
    summary: 'How members sign in to this workspace.',
    rows: [
      {
        label: 'Single sign-on (OIDC)',
        help: 'Discovery endpoint is configured; the code exchange still needs a provider.',
        control: 'select',
        value: 'Not configured',
      },
      {
        label: 'Require SSO for all members',
        help: 'Blocks email and password sign-in once a provider is connected.',
        control: 'toggle-off',
      },
      {
        label: 'Session lifetime',
        help: 'Members are signed out after this period of inactivity.',
        control: 'select',
        value: '12 hours',
      },
    ],
  },
  {
    title: 'Model routing',
    summary: 'Which model answers, and what it is allowed to see.',
    rows: [
      {
        label: 'Reasoning model',
        help: 'Drives query translation, drafting and the mock review board.',
        control: 'select',
        value: 'claude-sonnet-4-5',
      },
      {
        label: 'Retain prompts for debugging',
        help: 'Off by default so unpublished study data never leaves the audit boundary.',
        control: 'toggle-off',
      },
      {
        label: 'Cite every generated claim',
        help: 'Agents refuse to emit an unsourced factual sentence in drafts.',
        control: 'toggle-on',
      },
    ],
  },
  {
    title: 'Data & compliance',
    summary: 'Residency, retention and export controls.',
    rows: [
      {
        label: 'Data residency',
        help: 'Region where documents and embeddings are stored.',
        control: 'select',
        value: 'US-East',
      },
      {
        label: 'Audit retention',
        help: 'Append-only trail retention period.',
        control: 'select',
        value: '7 years',
      },
      {
        label: 'Block export of flagged compounds',
        help: 'Prevents ELN export while an open toxicity flag exists.',
        control: 'toggle-on',
      },
    ],
  },
  {
    title: 'Integration credentials',
    summary: 'Stored encrypted; values are never shown after saving.',
    rows: [
      {
        label: 'NCBI Entrez API key',
        help: 'Raises the PubMed rate limit from 3 to 10 requests per second.',
        control: 'text',
        value: '•••••••••••• 4f2a',
      },
      {
        label: 'Anthropic API key',
        help: 'Used for natural-language to Entrez translation.',
        control: 'text',
        value: '•••••••••••• 8E_A',
      },
      {
        label: 'Benchling tenant',
        help: 'ELN destination for protocol exports.',
        control: 'text',
        value: 'greytx.benchling.com',
      },
    ],
  },
];

function Control({ row }: { row: Row }) {
  if (row.control === 'toggle-on' || row.control === 'toggle-off') {
    const on = row.control === 'toggle-on';
    return (
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={row.label}
        className={[styles.toggle, on ? styles.toggleOn : ''].filter(Boolean).join(' ')}
      >
        <span className={styles.knob} />
      </button>
    );
  }
  return (
    <span className={row.control === 'text' ? styles.textValue : styles.select}>{row.value}</span>
  );
}

export function SettingsPage() {
  return (
    <PageCanvas
      title="Settings"
      description="Workspace-wide configuration. Changes apply to every member and are recorded in the audit trail."
      actions={<StatusPill tone="idle">No unsaved changes</StatusPill>}
      narrow
    >
      {GROUPS.map((group) => (
        <section key={group.title} className={styles.group}>
          <header className={styles.groupHeader}>
            <h2 className={styles.groupTitle}>{group.title}</h2>
            <p className={styles.groupSummary}>{group.summary}</p>
          </header>
          <div className={styles.rows}>
            {group.rows.map((row) => (
              <div key={row.label} className={styles.row}>
                <div className={styles.rowText}>
                  <span className={styles.rowLabel}>{row.label}</span>
                  <span className={styles.rowHelp}>{row.help}</span>
                </div>
                <Control row={row} />
              </div>
            ))}
          </div>
        </section>
      ))}
    </PageCanvas>
  );
}
