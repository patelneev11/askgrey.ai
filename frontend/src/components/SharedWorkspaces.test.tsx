import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import { setAccessToken } from '@/lib/session';
import type { WorkspaceDetail, WorkspaceMembership, WorkspaceRole } from '@/lib/workspaces';

import { SharedWorkspaces } from './SharedWorkspaces';

const workspace = vi.fn();
const createWorkspace = vi.fn();
const setActiveWorkspace = vi.fn();
const inviteToWorkspace = vi.fn();
const acceptWorkspaceInvite = vi.fn();
const setWorkspaceRole = vi.fn();
const removeWorkspaceMember = vi.fn();
const revokeWorkspaceInvite = vi.fn();
const transferWorkspace = vi.fn();
const updateWorkspace = vi.fn();
const deleteWorkspace = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      workspace: (...args: unknown[]) => workspace(...args),
      createWorkspace: (...args: unknown[]) => createWorkspace(...args),
      setActiveWorkspace: (...args: unknown[]) => setActiveWorkspace(...args),
      inviteToWorkspace: (...args: unknown[]) => inviteToWorkspace(...args),
      acceptWorkspaceInvite: (...args: unknown[]) => acceptWorkspaceInvite(...args),
      setWorkspaceRole: (...args: unknown[]) => setWorkspaceRole(...args),
      removeWorkspaceMember: (...args: unknown[]) => removeWorkspaceMember(...args),
      revokeWorkspaceInvite: (...args: unknown[]) => revokeWorkspaceInvite(...args),
      transferWorkspace: (...args: unknown[]) => transferWorkspace(...args),
      updateWorkspace: (...args: unknown[]) => updateWorkspace(...args),
      deleteWorkspace: (...args: unknown[]) => deleteWorkspace(...args),
    },
  };
});

const MEMBERSHIP: WorkspaceMembership = {
  workspaces: [
    {
      id: 'ws-1',
      name: 'Discovery chemistry',
      role: 'owner',
      seat_limit: 5,
      seats_used: 3,
      member_count: 2,
      created_at: '2026-08-01T00:00:00Z',
    },
  ],
  active_workspace_id: 'ws-1',
};

function detail(role: WorkspaceRole = 'owner'): WorkspaceDetail {
  return {
    id: 'ws-1',
    name: 'Discovery chemistry',
    role,
    seat_limit: 5,
    seats_used: 3,
    member_count: 2,
    created_at: '2026-08-01T00:00:00Z',
    members: [
      {
        user_id: 'user-me',
        email: 'chemist@askgrey.ai',
        full_name: 'Dana Okoye',
        role: role === 'owner' ? 'owner' : role,
        joined_at: '2026-08-01T00:00:00Z',
        is_owner: role === 'owner',
      },
      {
        user_id: 'user-them',
        email: 'colleague@lab.org',
        full_name: 'Sam Reyes',
        role: 'member',
        joined_at: '2026-08-02T00:00:00Z',
        is_owner: false,
      },
    ],
    invites: [
      {
        id: 'invite-1',
        email: 'pending@lab.org',
        role: 'viewer',
        invited_by_user_id: 'user-me',
        created_at: '2026-08-03T00:00:00Z',
        expires_at: '2026-08-17T00:00:00Z',
      },
    ],
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  [
    workspace,
    createWorkspace,
    setActiveWorkspace,
    inviteToWorkspace,
    acceptWorkspaceInvite,
    setWorkspaceRole,
    removeWorkspaceMember,
    revokeWorkspaceInvite,
    transferWorkspace,
    updateWorkspace,
    deleteWorkspace,
  ].forEach((mock) => mock.mockReset());
  workspace.mockResolvedValue(detail());
  setActiveWorkspace.mockResolvedValue(MEMBERSHIP);
  createWorkspace.mockResolvedValue(MEMBERSHIP.workspaces[0]);
  inviteToWorkspace.mockResolvedValue({
    invite: detail().invites[0],
    token: 'invite-token-abc',
    workspace_name: 'Discovery chemistry',
    delivered: false,
  });
});

/** Shows the query string the router is on, so a test can watch a token leave the URL. */
function QueryProbe() {
  return <span data-testid="query">{useLocation().search}</span>;
}

/** The panel reads an emailed invitation out of the query string, so it needs a router. */
function mount(membership: WorkspaceMembership, onChanged = vi.fn(), url = '/workspace') {
  render(
    <MemoryRouter initialEntries={[url]}>
      <SharedWorkspaces membership={membership} email="chemist@askgrey.ai" onChanged={onChanged} />
      <QueryProbe />
    </MemoryRouter>,
  );
  return onChanged;
}

describe('shared workspaces', () => {
  it('says work is private, and offers no seats, until a workspace exists', () => {
    mount({ workspaces: [], active_workspace_id: null });

    expect(screen.getByText(/visible to this account only/i)).toBeInTheDocument();
    expect(screen.queryByText(/seats used/i)).not.toBeInTheDocument();
    expect(workspace).not.toHaveBeenCalled();
  });

  it('switches back to private, which is a decision recorded on the account', async () => {
    const onChanged = mount(MEMBERSHIP);

    await userEvent.click(screen.getByRole('button', { name: 'Private' }));

    expect(setActiveWorkspace).toHaveBeenCalledWith(null, 'token-123');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('counts pending invitations against the seat limit', async () => {
    mount(MEMBERSHIP);

    expect(
      await screen.findByText(/3 of 5 seats used — members plus invitations still open/i),
    ).toBeInTheDocument();
  });

  it('shows an issued invitation once, because the server keeps only its hash', async () => {
    mount(MEMBERSHIP);
    await screen.findByText(/seats used/i);

    await userEvent.type(screen.getByLabelText(/invite by email/i), 'new@lab.org');
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }));

    expect(inviteToWorkspace).toHaveBeenCalledWith('ws-1', 'new@lab.org', 'member', 'token-123');
    expect(await screen.findByText('invite-token-abc')).toBeInTheDocument();
    expect(screen.getByText(/shown once and cannot be read again/i)).toBeInTheDocument();
  });

  it('says an invitation was emailed, and still shows the token as the only fallback', async () => {
    inviteToWorkspace.mockResolvedValue({
      invite: detail().invites[0],
      token: 'invite-token-abc',
      workspace_name: 'Discovery chemistry',
      delivered: true,
    });
    mount(MEMBERSHIP);
    await screen.findByText(/seats used/i);

    await userEvent.type(screen.getByLabelText(/invite by email/i), 'new@lab.org');
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }));

    expect(await screen.findByText(/emailed to pending@lab.org/i)).toBeInTheDocument();
    // Mail can be silently dropped, so the one copy of the token stays on screen either way.
    expect(screen.getByText('invite-token-abc')).toBeInTheDocument();
  });

  it('fills in a token arriving from an emailed link, and takes it out of the URL', async () => {
    acceptWorkspaceInvite.mockResolvedValue(MEMBERSHIP.workspaces[0]);
    mount(MEMBERSHIP, vi.fn(), '/workspace?invite=mailed-token-xyz');

    const field = await screen.findByPlaceholderText(/paste the invitation token/i);
    expect(field).toHaveValue('mailed-token-xyz');
    // A link that spent its own token on a mail-client prefetch would burn the seat unseen.
    expect(acceptWorkspaceInvite).not.toHaveBeenCalled();
    // Out of the URL, so it is not left in history, a bookmark or a screenshot.
    await waitFor(() => expect(screen.getByTestId('query')).toHaveTextContent(''));
    expect(screen.getByTestId('query').textContent).not.toContain('mailed-token-xyz');
    expect(screen.getByText(/invitation from your email is ready/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Join' }));
    expect(acceptWorkspaceInvite).toHaveBeenCalledWith('mailed-token-xyz', 'token-123');
  });

  it('offers ownership transfer and deletion to the owner alone', async () => {
    mount(MEMBERSHIP);
    await screen.findByText(/seats used/i);

    expect(screen.getByRole('button', { name: 'Make owner' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete workspace' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument();
  });

  it('gives a viewer no seat controls, and leaving instead of removing', async () => {
    workspace.mockResolvedValue(detail('viewer'));
    mount({
      workspaces: [{ ...MEMBERSHIP.workspaces[0], role: 'viewer' }],
      active_workspace_id: 'ws-1',
    });
    await screen.findByText(/seats used/i);

    expect(screen.queryByLabelText(/invite by email/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete workspace' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Leave' })).toBeInTheDocument();
  });

  it('re-reads the workspace after a removal, so a done action does not look ignored', async () => {
    removeWorkspaceMember.mockResolvedValue(undefined);
    const shrunk = detail();
    shrunk.members = shrunk.members.slice(0, 1);
    shrunk.seats_used = 2;
    workspace.mockResolvedValueOnce(detail()).mockResolvedValue(shrunk);
    mount(MEMBERSHIP);
    await screen.findByText('colleague@lab.org');

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }));

    await waitFor(() => expect(screen.queryByText('colleague@lab.org')).not.toBeInTheDocument());
    expect(screen.getByText(/2 of 5 seats used/i)).toBeInTheDocument();
  });

  it('settles into private work after a deletion instead of reporting the workspace gone', async () => {
    deleteWorkspace.mockResolvedValue(undefined);
    workspace
      .mockResolvedValueOnce(detail())
      .mockRejectedValue(new ApiError('no workspace with that id', 404));
    mount(MEMBERSHIP);
    await screen.findByText('colleague@lab.org');

    await userEvent.click(screen.getByRole('button', { name: 'Delete workspace' }));

    await waitFor(() => expect(screen.queryByText('colleague@lab.org')).not.toBeInTheDocument());
    expect(screen.queryByText(/no workspace with that id/i)).not.toBeInTheDocument();
  });

  it('reports a rejected change rather than pretending it landed', async () => {
    createWorkspace.mockRejectedValue(new Error('you already own too many workspaces'));
    const onChanged = mount(MEMBERSHIP);

    await userEvent.type(screen.getByLabelText(/new workspace/i), 'Second lab');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    expect(await screen.findByText(/already own too many workspaces/i)).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
  });
});
