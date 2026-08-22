import { useCallback, useEffect, useState } from 'react';

import { EmptyState } from '@/components/EmptyState';
import { Meter } from '@/components/Meter';
import { PageCanvas } from '@/components/PageCanvas';
import { SharedWorkspaces } from '@/components/SharedWorkspaces';
import { StatusPill } from '@/components/StatusPill';
import { api, type AccountOverview } from '@/lib/api';
import type { ArtifactKind } from '@/lib/library';
import { getAccessToken } from '@/lib/session';

import styles from './WorkspacePage.module.css';

/** Which tab produced a saved artifact, so the counts read as work rather than as row types. */
const WORK_LABELS: Record<ArtifactKind, string> = {
  screening_profile: 'Screening — compound profiles',
  screening_descriptors: 'Screening — descriptor reads',
  screening_admet: 'Screening — ADMET predictions',
  screening_suggestions: 'Screening — substituent suggestions',
  screening_patents: 'Screening — patent landscapes',
  regulatory_preclinical: 'Regulatory — preclinical reports',
  regulatory_ind: 'Regulatory — IND sections',
  grants_eligibility: 'Grants — eligibility screens',
  grants_budget: 'Grants — budgets',
  grants_review_board: 'Grants — review board runs',
};

function initialsOf(name: string, email: string): string {
  const source = name.trim() || email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase();
}

function dateOf(iso: string | null): string {
  if (!iso) return '—';
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

/** Bytes as the researcher would say them. Stored papers are megabytes, never gigabytes. */
function sizeOf(bytes: number): string {
  if (bytes === 0) return '0 MB';
  const mb = bytes / 1_000_000;
  return mb < 0.1 ? '<0.1 MB' : `${mb.toFixed(1)} MB`;
}

/** How much of the retention window the paper closest to expiry has left. */
function retentionFraction(storage: AccountOverview['storage']): number {
  if (!storage.next_expiry || storage.retention_days <= 0) return 0;
  const daysLeft = (new Date(storage.next_expiry).getTime() - Date.now()) / 86_400_000;
  if (Number.isNaN(daysLeft)) return 0;
  return Math.min(1, Math.max(0, daysLeft / storage.retention_days));
}

function daysLeftOf(storage: AccountOverview['storage']): string {
  if (!storage.next_expiry) return 'Nothing stored';
  const daysLeft = Math.ceil(
    (new Date(storage.next_expiry).getTime() - Date.now()) / 86_400_000,
  );
  return `${Math.max(0, daysLeft)} of ${storage.retention_days} days left`;
}

/**
 * This account, counted from its own rows, and the workspaces it shares work through.
 *
 * Third-party integrations are still absent: none are built, and a connected-systems list that
 * connects to nothing is the claim this page exists to avoid making.
 */
export function WorkspacePage() {
  const [overview, setOverview] = useState<AccountOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        setError(cause instanceof Error ? cause.message : 'Could not load this workspace.');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => load(), [load]);

  // A membership change moves which saved work every tab can see, so the page is re-read rather
  // than patched from the response of whichever button was pressed.
  const reload = useCallback(() => {
    load();
  }, [load]);

  const work = overview
    ? (Object.entries(overview.saved_work.counts) as [ArtifactKind, number][]).sort(
        ([, left], [, right]) => right - left,
      )
    : [];

  return (
    <PageCanvas
      title="Workspace"
      description="Who is signed in, what this account is storing, the work it has saved for the agents to reference, and which data sources this deployment can reach."
      actions={
        loading ? (
          <StatusPill tone="running">Loading</StatusPill>
        ) : (
          overview && <StatusPill tone="validated">{overview.platform.environment}</StatusPill>
        )
      }
    >
      {error && (
        <EmptyState title="This workspace could not be loaded">
          <p>{error}</p>
        </EmptyState>
      )}

      {overview && (
        <>
          <section className={styles.identity}>
            <span className={styles.monogram} aria-hidden="true">
              {initialsOf(overview.account.full_name, overview.account.email)}
            </span>
            <dl className={styles.facts}>
              <div>
                <dt>Signed in as</dt>
                <dd>{overview.account.email}</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>{overview.account.role}</dd>
              </div>
              <div>
                <dt>Sign-in</dt>
                <dd>{overview.account.provider === 'oidc' ? 'Single sign-on' : 'Password'}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{dateOf(overview.account.created_at)}</dd>
              </div>
            </dl>
            <div className={styles.retention}>
              <Meter
                label={`Stored papers · ${sizeOf(overview.storage.stored_bytes)}`}
                value={daysLeftOf(overview.storage)}
                fraction={retentionFraction(overview.storage)}
                tone="pipeline"
              />
            </div>
          </section>

          <SharedWorkspaces
            membership={overview.workspaces}
            email={overview.account.email}
            onChanged={reload}
          />

          <section>
            <h2 className={styles.sectionTitle}>Saved work</h2>
            {overview.saved_work.total === 0 && (
              <EmptyState title="Nothing saved yet">
                <p>
                  Screening profiles, regulatory drafts, eligibility screens and budgets appear
                  here once you save them from their tab. Saved work survives a reload and is what
                  a future chat can reference.
                </p>
              </EmptyState>
            )}
            <table className={styles.members}>
              <thead>
                <tr>
                  <th scope="col">What</th>
                  <th scope="col">Saved</th>
                </tr>
              </thead>
              <tbody>
                {work.map(([kind, count]) => (
                  <tr key={kind}>
                    <th scope="row">
                      <span className={styles.memberName}>{WORK_LABELS[kind] ?? kind}</span>
                    </th>
                    <td>
                      <span className={styles.role}>{count}</span>
                    </td>
                  </tr>
                ))}
                <tr>
                  <th scope="row">
                    <span className={styles.memberName}>Stored papers (Literature)</span>
                    <span className={styles.memberEmail}>
                      Encrypted at rest, deleted after {overview.storage.retention_days} days
                    </span>
                  </th>
                  <td>
                    <span className={styles.role}>{overview.storage.stored_papers}</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">
                    <span className={styles.memberName}>Recorded audit events</span>
                  </th>
                  <td>
                    <span className={styles.role}>{overview.audit_events}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            {overview.saved_work.last_saved_at && (
              <p className={styles.muted}>
                Last saved {dateOf(overview.saved_work.last_saved_at)}
              </p>
            )}
          </section>

          <section>
            <h2 className={styles.sectionTitle}>Data sources</h2>
            <ul className={styles.integrations}>
              {overview.upstreams.map((upstream) => (
                <li key={upstream.name} className={styles.integration}>
                  <div>
                    <span className={styles.integrationName}>{upstream.name}</span>
                    <span className={styles.integrationDetail}>{upstream.detail}</span>
                  </div>
                  <StatusPill tone={upstream.configured ? 'validated' : 'idle'}>
                    {upstream.configured ? 'Available' : 'Not configured'}
                  </StatusPill>
                </li>
              ))}
            </ul>
            <p className={styles.muted}>
              These are the public sources the agents read from — not a document vault or an ELN.
              Third-party integrations are not built: an ELN export is a payload this app can
              build, not a system it is connected to.
            </p>
          </section>
        </>
      )}
    </PageCanvas>
  );
}
