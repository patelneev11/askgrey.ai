import { useCallback, useEffect, useState } from 'react';

import { EmptyState } from '@/components/EmptyState';
import { PageCanvas } from '@/components/PageCanvas';
import { StatusPill } from '@/components/StatusPill';
import { api, type AuditEvent, type AuditKind } from '@/lib/api';
import { getAccessToken } from '@/lib/session';

import styles from './AuditPage.module.css';

const FILTERS: { label: string; kind: AuditKind | null }[] = [
  { label: 'All activity', kind: null },
  { label: 'Agent runs', kind: 'agent' },
  { label: 'Human actions', kind: 'human' },
  { label: 'Exports', kind: 'export' },
];

/**
 * Plain language for the event names the backend records (`app.core.audit`). An unknown name
 * is shown as recorded rather than hidden: a missing label must not lose an event.
 */
const ACTIONS: Record<string, string> = {
  'auth.register': 'Created this workspace',
  'auth.login': 'Signed in',
  'auth.refresh': 'Renewed a session',
  'auth.logout': 'Signed out',
  'auth.logout_all': 'Signed out of every device',
  'document.sent_to_llm': 'Sent a document to the model vendor',
  'grant_section.sent_to_llm': 'Sent a draft section to the model vendor',
  'export.downloaded': 'Downloaded a review table',
  'grants.budget_exported': 'Downloaded a grant budget',
  'literature.document_read': 'Opened a stored paper',
  'literature.document_deleted': 'Deleted a stored paper',
  'literature.workspace_deleted': 'Cleared the Literature workspace',
};

/** Who or what the entry is about. The backend classifies this on write. */
const ACTORS: Record<AuditKind, string> = {
  agent: 'Agent',
  human: 'You',
  export: 'You',
};

function timeOf(occurredAt: string): string {
  const at = new Date(occurredAt);
  return Number.isNaN(at.getTime())
    ? occurredAt
    : at.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
}

function dateOf(occurredAt: string): string {
  const at = new Date(occurredAt);
  return Number.isNaN(at.getTime()) ? occurredAt : at.toLocaleDateString();
}

/** The recorded provenance, as `key value` pairs. Never document text — the API sends none. */
function detailOf(event: AuditEvent): string {
  const parts = Object.entries(event.detail).map(([key, value]) => `${key} ${String(value)}`);
  if (event.client_ip) parts.push(`from ${event.client_ip}`);
  return parts.join(' · ');
}

export function AuditPage() {
  const [kind, setKind] = useState<AuditKind | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((selected: AuditKind | null) => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .auditEvents(selected ?? undefined, getAccessToken())
      .then((feed) => {
        if (!live) return;
        setEvents(feed.events);
        setRetentionDays(feed.retention_days);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setEvents([]);
        setError(cause instanceof Error ? cause.message : 'Could not load the audit trail.');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => load(kind), [kind, load]);

  return (
    <PageCanvas
      title="Audit Trails"
      description="Every sign-in, document access, model call and export recorded for this workspace, newest first."
      actions={
        <div className={styles.filters}>
          {loading && <StatusPill tone="running">Loading</StatusPill>}
          {FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              aria-pressed={filter.kind === kind}
              onClick={() => setKind(filter.kind)}
              className={[styles.filter, filter.kind === kind ? styles.filterActive : '']
                .filter(Boolean)
                .join(' ')}
            >
              {filter.label}
            </button>
          ))}
        </div>
      }
    >
      {error && (
        <EmptyState title="The audit trail could not be loaded">
          <p>{error}</p>
        </EmptyState>
      )}
      {!error && !loading && events.length === 0 && (
        <EmptyState title="No recorded activity yet">
          <p>
            Signing in, opening a stored paper, sending a document to the model vendor and
            downloading a table are each recorded here as they happen. Only this workspace&apos;s
            own events are shown.
          </p>
        </EmptyState>
      )}
      <ol className={styles.timeline}>
        {events.map((event) => (
          <li key={event.id} className={styles.event}>
            <time className={styles.time} dateTime={event.occurred_at}>
              {timeOf(event.occurred_at)}
            </time>
            <span className={[styles.rail, styles[event.kind]].join(' ')} aria-hidden="true" />
            <div className={styles.body}>
              <p className={styles.line}>
                <span className={styles.actor}>{ACTORS[event.kind]}</span>
                <span className={styles.action}>{ACTIONS[event.event] ?? event.event}</span>
                {event.outcome !== 'success' && (
                  <StatusPill tone="warning">{event.outcome}</StatusPill>
                )}
              </p>
              <p className={styles.target}>
                {dateOf(event.occurred_at)}
                {detailOf(event) && ` · ${detailOf(event)}`}
              </p>
            </div>
            <code className={styles.hash}>{event.id.slice(0, 7)}</code>
          </li>
        ))}
      </ol>
      {retentionDays !== null && (
        <p className={styles.retention}>
          Entries are kept for {retentionDays} days and then deleted. This is an operational
          security log, not a 21 CFR Part 11 archive: it is not immutable, and it does not record
          document contents, prompts or extracted values.
        </p>
      )}
    </PageCanvas>
  );
}
