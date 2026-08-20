import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { PageCanvas } from '@/components/PageCanvas';
import { StatusPill } from '@/components/StatusPill';
import { api, type AccountOverview } from '@/lib/api';
import { useOnboarding } from '@/lib/onboarding-context';
import { getAccessToken, notifySessionExpired } from '@/lib/session';

import styles from './SettingsPage.module.css';

interface Row {
  label: string;
  help: string;
  value: string;
}

/** What sealing scheme the deployment is actually using, in the reader's terms. */
const ENCRYPTION: Record<string, string> = {
  kms: 'AWS KMS — a data key per document, wrapped by your key',
  'local-key': 'AES-GCM under a dedicated document key',
  'derived-from-jwt-secret': 'AES-GCM under a key derived from the JWT secret (development only)',
};

const STORAGE: Record<string, string> = {
  s3: 'Amazon S3 — ciphertext in your bucket, metadata in the database',
  database: 'The application database (fine for a clone; every backup carries the PDFs)',
};

function whenOf(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function authenticationRows(overview: AccountOverview): Row[] {
  return [
    {
      label: 'Sign-in method',
      help: 'How this account authenticates today.',
      value: overview.account.provider === 'oidc' ? 'Single sign-on (OIDC)' : 'Email and password',
    },
    {
      label: 'Access token lifetime',
      help: 'How long a request credential is valid before the browser silently renews it.',
      value: `${overview.platform.access_token_ttl_minutes} minutes`,
    },
    {
      label: 'Sign-in lifetime',
      help: 'A session not renewed within this window has to sign in again.',
      value: `${overview.platform.refresh_token_ttl_days} days`,
    },
  ];
}

function modelRows(overview: AccountOverview): Row[] {
  return [
    {
      label: 'Reasoning model',
      help: 'Query translation, column extraction, drafting and review all call this model.',
      value: overview.platform.llm_model,
    },
    {
      label: 'Model credentials',
      help: 'Without a server-side key, extraction and drafting return an unavailable state.',
      value: overview.platform.extraction_available ? 'Configured' : 'Not configured',
    },
    {
      label: 'Daily model call budget',
      help: 'Calls beyond this are refused for the rest of the day, so a loop cannot run up a bill.',
      value: `${overview.platform.llm_daily_call_budget} calls`,
    },
  ];
}

function dataRows(overview: AccountOverview): Row[] {
  return [
    {
      label: 'Stored paper encryption',
      help: 'Uploaded PDFs are encrypted by the app before they are stored anywhere.',
      value: ENCRYPTION[overview.platform.document_encryption] ?? overview.platform.document_encryption,
    },
    {
      label: 'Stored paper location',
      help: 'Where the encrypted bytes are kept. Encryption is the same either way.',
      value: STORAGE[overview.platform.document_storage] ?? overview.platform.document_storage,
    },
    {
      label: 'Stored paper retention',
      help: 'A stored paper stops being served and is deleted after this window.',
      value: `${overview.storage.retention_days} days`,
    },
    {
      label: 'Audit retention',
      help: 'How long the security log keeps an entry. Operational log, not a 21 CFR Part 11 archive.',
      value: `${overview.platform.audit_retention_days} days`,
    },
    {
      label: 'Deployment',
      help: 'Which environment you are signed in to, and the build it is running.',
      value: `${overview.platform.environment} · ${overview.platform.release}`,
    },
  ];
}

export function SettingsPage() {
  const { restartTour } = useOnboarding();
  const [overview, setOverview] = useState<AccountOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const load = useCallback(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .accountOverview(getAccessToken())
      .then((loaded) => {
        if (live) setOverview(loaded);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setOverview(null);
        setError(cause instanceof Error ? cause.message : 'Could not load these settings.');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => load(), [load]);

  /**
   * Revoking every session includes this one, so the app has to stop rendering a workspace it
   * can no longer renew — the same path a server-rejected session takes.
   */
  const signOutEverywhere = useCallback(async () => {
    setSigningOut(true);
    try {
      await api.logoutAll(getAccessToken());
      notifySessionExpired();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not revoke the other sessions.');
    } finally {
      setSigningOut(false);
    }
  }, []);

  const groups: { title: string; summary: string; rows: Row[] }[] = overview
    ? [
        {
          title: 'Authentication',
          summary: 'How you sign in, and how long a sign-in lasts.',
          rows: authenticationRows(overview),
        },
        {
          title: 'Model routing',
          summary: 'Which model this deployment calls, and what it is allowed to spend.',
          rows: modelRows(overview),
        },
        {
          title: 'Data handling',
          summary: 'How stored papers are sealed, and how long anything is kept.',
          rows: dataRows(overview),
        },
      ]
    : [];

  return (
    <PageCanvas
      title="Settings"
      description="What this deployment is configured to do, read from the running server — not a stored preference you can edit here."
      actions={
        loading ? <StatusPill tone="running">Loading</StatusPill> : <StatusPill tone="idle">Read-only</StatusPill>
      }
      narrow
    >
      {error && (
        <EmptyState title="These settings could not be loaded">
          <p>{error}</p>
        </EmptyState>
      )}

      {groups.map((group) => (
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
                <span className={styles.value}>{row.value}</span>
              </div>
            ))}
          </div>
        </section>
      ))}

      {overview && (
        <section className={styles.group}>
          <header className={styles.groupHeader}>
            <h2 className={styles.groupTitle}>Active sign-ins</h2>
            <p className={styles.groupSummary}>
              Every browser currently able to renew this account&apos;s session. Device and location
              are not shown because the app never collected them.
            </p>
          </header>
          <div className={styles.rows}>
            {overview.sessions.map((session) => (
              <div key={session.id} className={styles.row}>
                <div className={styles.rowText}>
                  <span className={styles.rowLabel}>Signed in {whenOf(session.issued_at)}</span>
                  <span className={styles.rowHelp}>
                    Renewable until {whenOf(session.expires_at)}
                  </span>
                </div>
                <span className={styles.textValue}>{session.id.slice(0, 7)}</span>
              </div>
            ))}
            <div className={styles.row}>
              <div className={styles.rowText}>
                <span className={styles.rowLabel}>Sign out everywhere</span>
                <span className={styles.rowHelp}>
                  Revokes all {overview.sessions.length} sign-ins, including this one.
                </span>
              </div>
              <Button size="sm" onClick={() => void signOutEverywhere()} disabled={signingOut}>
                {signingOut ? 'Signing out…' : 'Sign out everywhere'}
              </Button>
            </div>
          </div>
        </section>
      )}

      {/* A tour you cannot reopen is a tour you have to absorb first time. */}
      <section className={styles.group}>
        <header className={styles.groupHeader}>
          <h2 className={styles.groupTitle}>Onboarding</h2>
          <p className={styles.groupSummary}>
            Replay the first-run walkthrough of what AskGrey does and where to start.
          </p>
        </header>
        <div className={styles.rows}>
          <div className={styles.row}>
            <div className={styles.rowText}>
              <span className={styles.rowLabel}>First-run tour</span>
              <span className={styles.rowHelp}>Four screens, under two minutes, skippable.</span>
            </div>
            <Button size="sm" onClick={restartTour}>
              Replay tour
            </Button>
          </div>
        </div>
      </section>

      <p className={styles.footnote}>
        Editing these from the app is not built: they are deployment configuration, and an account
        cannot change them for itself. Shared workspaces, per-member roles, SSO enforcement and
        data residency selection do not exist yet, so they are absent rather than shown as controls
        that do nothing.
      </p>
    </PageCanvas>
  );
}
