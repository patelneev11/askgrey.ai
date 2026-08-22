import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { StatusPill } from '@/components/StatusPill';
import { api } from '@/lib/api';
import { getAccessToken } from '@/lib/session';
import {
  ASSIGNABLE_ROLES,
  mayAdminister,
  ROLE_LABELS,
  type WorkspaceDetail,
  type WorkspaceMembership,
  type WorkspaceRole,
} from '@/lib/workspaces';

import styles from './SharedWorkspaces.module.css';

interface SharedWorkspacesProps {
  membership: WorkspaceMembership;
  /** This account's own address, so it can tell its own row from a colleague's. */
  email: string;
  /** Re-read the overview: switching workspace changes which saved work every tab shows. */
  onChanged: () => void;
}

function dayOf(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

function messageOf(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * The workspaces this account belongs to, and the seats in the one it is working in.
 *
 * A workspace shares findings — saved artifacts, protocols, drafts, budgets — and never stored
 * papers, whose ciphertext stays bound to the account that uploaded them. Switching is a server
 * decision recorded on the account, not a client preference, so every tab and the assistant see
 * the same scope on their next request.
 */
export function SharedWorkspaces({ membership, email, onChanged }: SharedWorkspacesProps) {
  const activeId = membership.active_workspace_id;
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('member');
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [redeemToken, setRedeemToken] = useState('');

  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      return;
    }
    let live = true;
    api
      .workspace(activeId, getAccessToken())
      .then((loaded) => {
        if (live) setDetail(loaded);
      })
      .catch((cause: unknown) => {
        if (live) setError(messageOf(cause, 'Could not load this workspace.'));
      });
    return () => {
      live = false;
    };
  }, [activeId]);

  /** Every mutation ends the same way: re-read the account, because the scope may have moved. */
  const run = useCallback(
    async (action: () => Promise<unknown>, fallback: string) => {
      setBusy(true);
      setError(null);
      try {
        await action();
        onChanged();
      } catch (cause: unknown) {
        setError(messageOf(cause, fallback));
      } finally {
        setBusy(false);
      }
    },
    [onChanged],
  );

  const create = () =>
    run(async () => {
      await api.createWorkspace(name.trim(), 5, getAccessToken());
      setName('');
    }, 'Could not create that workspace.');

  const accept = () =>
    run(async () => {
      await api.acceptWorkspaceInvite(redeemToken.trim(), getAccessToken());
      setRedeemToken('');
    }, 'Could not accept that invitation.');

  const invite = () =>
    run(async () => {
      if (!activeId) return;
      const created = await api.inviteToWorkspace(
        activeId,
        inviteEmail.trim(),
        inviteRole,
        getAccessToken(),
      );
      setIssuedToken(created.token);
      setInviteEmail('');
    }, 'Could not invite that address.');

  const administers = detail !== null && mayAdminister(detail.role);
  const owns = detail?.role === 'owner';

  return (
    <section>
      <h2 className={styles.sectionTitle}>Workspaces</h2>

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.switcher} role="group" aria-label="Active workspace">
        <Button
          variant={activeId === null ? 'primary' : 'secondary'}
          size="sm"
          disabled={busy || activeId === null}
          onClick={() => run(() => api.setActiveWorkspace(null, getAccessToken()), 'Could not switch.')}
        >
          Private
        </Button>
        {membership.workspaces.map((workspace) => (
          <Button
            key={workspace.id}
            variant={workspace.id === activeId ? 'primary' : 'secondary'}
            size="sm"
            disabled={busy || workspace.id === activeId}
            onClick={() =>
              run(
                () => api.setActiveWorkspace(workspace.id, getAccessToken()),
                'Could not switch workspace.',
              )
            }
          >
            {workspace.name}
          </Button>
        ))}
      </div>

      <p className={styles.muted}>
        {activeId === null
          ? 'Working privately: saved work is visible to this account only.'
          : 'Work saved from any tab while this workspace is active is visible to its members. Stored papers stay private to whoever uploaded them.'}
      </p>

      {membership.workspaces.length === 0 && (
        <EmptyState title="No shared workspace yet">
          <p>
            Create one to share saved screens, protocols, drafts and budgets with colleagues, or
            paste an invitation you were given.
          </p>
        </EmptyState>
      )}

      <div className={styles.forms}>
        <label className={styles.field}>
          <span>New workspace</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Discovery chemistry"
            maxLength={200}
          />
        </label>
        <Button variant="primary" size="sm" disabled={busy || !name.trim()} onClick={create}>
          Create
        </Button>

        <label className={styles.field}>
          <span>Invitation you were given</span>
          <input
            value={redeemToken}
            onChange={(event) => setRedeemToken(event.target.value)}
            placeholder="Paste the invitation token"
          />
        </label>
        <Button size="sm" disabled={busy || !redeemToken.trim()} onClick={accept}>
          Join
        </Button>
      </div>

      {detail && (
        <>
          <div className={styles.seats}>
            <StatusPill tone="validated">{ROLE_LABELS[detail.role]}</StatusPill>
            <span className={styles.muted}>
              {detail.seats_used} of {detail.seat_limit} seats used — members plus invitations still
              open
            </span>
          </div>

          <table className={styles.members}>
            <thead>
              <tr>
                <th scope="col">Member</th>
                <th scope="col">Role</th>
                <th scope="col">Joined</th>
                <th scope="col"> </th>
              </tr>
            </thead>
            <tbody>
              {detail.members.map((member) => (
                <tr key={member.user_id}>
                  <th scope="row">
                    <span className={styles.memberName}>{member.full_name || member.email}</span>
                    <span className={styles.memberEmail}>{member.email}</span>
                  </th>
                  <td>
                    {administers && !member.is_owner ? (
                      <select
                        aria-label={`Role for ${member.email}`}
                        value={member.role}
                        disabled={busy}
                        onChange={(event) =>
                          run(
                            () =>
                              api.setWorkspaceRole(
                                detail.id,
                                member.user_id,
                                event.target.value as WorkspaceRole,
                                getAccessToken(),
                              ),
                            'Could not change that role.',
                          )
                        }
                      >
                        {ASSIGNABLE_ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className={styles.role}>{member.role}</span>
                    )}
                  </td>
                  <td className={styles.muted}>{dayOf(member.joined_at)}</td>
                  <td className={styles.rowActions}>
                    {owns && !member.is_owner && (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () =>
                              api.transferWorkspace(detail.id, member.user_id, getAccessToken()),
                            'Could not transfer this workspace.',
                          )
                        }
                      >
                        Make owner
                      </Button>
                    )}
                    {!member.is_owner && (administers || member.email === email) && (
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () =>
                              api.removeWorkspaceMember(
                                detail.id,
                                member.user_id,
                                getAccessToken(),
                              ),
                            'Could not remove that member.',
                          )
                        }
                      >
                        {member.email === email ? 'Leave' : 'Remove'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {administers && (
            <>
              <div className={styles.forms}>
                <label className={styles.field}>
                  <span>Invite by email</span>
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="colleague@lab.org"
                  />
                </label>
                <label className={styles.field}>
                  <span>As</span>
                  <select
                    aria-label="Role for the invited member"
                    value={inviteRole}
                    onChange={(event) => setInviteRole(event.target.value as WorkspaceRole)}
                  >
                    {ASSIGNABLE_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={busy || !inviteEmail.trim()}
                  onClick={invite}
                >
                  Invite
                </Button>
              </div>

              {issuedToken && (
                <p className={styles.token}>
                  Send this invitation to them yourself — it is shown once and cannot be read
                  again: <code>{issuedToken}</code>
                </p>
              )}

              {detail.invites.length > 0 && (
                <table className={styles.members}>
                  <thead>
                    <tr>
                      <th scope="col">Invited</th>
                      <th scope="col">Role</th>
                      <th scope="col">Expires</th>
                      <th scope="col"> </th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.invites.map((pending) => (
                      <tr key={pending.id}>
                        <th scope="row">
                          <span className={styles.memberName}>{pending.email}</span>
                        </th>
                        <td>
                          <span className={styles.role}>{pending.role}</span>
                        </td>
                        <td className={styles.muted}>{dayOf(pending.expires_at)}</td>
                        <td className={styles.rowActions}>
                          <Button
                            variant="danger"
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              run(
                                () =>
                                  api.revokeWorkspaceInvite(
                                    detail.id,
                                    pending.id,
                                    getAccessToken(),
                                  ),
                                'Could not revoke that invitation.',
                              )
                            }
                          >
                            Revoke
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {owns && (
            <div className={styles.ownerActions}>
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  run(
                    () =>
                      api.updateWorkspace(
                        detail.id,
                        { seat_limit: detail.seat_limit + 1 },
                        getAccessToken(),
                      ),
                    'Could not change the seat limit.',
                  )
                }
              >
                Add a seat
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={busy}
                onClick={() =>
                  run(
                    () => api.deleteWorkspace(detail.id, getAccessToken()),
                    'Could not delete this workspace.',
                  )
                }
              >
                Delete workspace
              </Button>
              <span className={styles.muted}>
                Deleting removes the work its members shared into it. Private work is untouched.
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
