/**
 * Shared workspaces: the memberships that scope saved work, and what each role may do.
 *
 * A workspace shares findings — saved artifacts, protocols, drafts, budgets — and not stored
 * papers, whose ciphertext stays bound to the account that uploaded them. Mirrors
 * `backend/app/services/workspaces.py`; the server decides every one of these rules again, so
 * the helpers here only decide which controls are worth rendering.
 */

export type WorkspaceRole = 'viewer' | 'member' | 'admin' | 'owner';

/** Mirrors `WorkspaceSummary`. `seats_used` counts members plus invitations still open. */
export interface WorkspaceSummary {
  id: string;
  name: string;
  role: WorkspaceRole;
  seat_limit: number;
  seats_used: number;
  member_count: number;
  created_at: string;
}

export interface WorkspaceMemberSummary {
  user_id: string;
  email: string;
  full_name: string;
  role: WorkspaceRole;
  joined_at: string;
  is_owner: boolean;
}

/** A pending invitation. The token itself is returned once, at creation, and never again. */
export interface WorkspaceInviteSummary {
  id: string;
  email: string;
  role: WorkspaceRole;
  invited_by_user_id: string;
  created_at: string;
  expires_at: string;
}

export interface WorkspaceDetail extends WorkspaceSummary {
  members: WorkspaceMemberSummary[];
  /** Empty for anyone below admin: who has been approached is not a member's business. */
  invites: WorkspaceInviteSummary[];
}

export interface WorkspaceMembership {
  workspaces: WorkspaceSummary[];
  active_workspace_id: string | null;
}

export interface CreatedWorkspaceInvite {
  invite: WorkspaceInviteSummary;
  token: string;
}

const RANKS: Record<WorkspaceRole, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

export function atLeast(role: WorkspaceRole, floor: WorkspaceRole): boolean {
  return RANKS[role] >= RANKS[floor];
}

/** Viewers read shared work; everyone else may save into it. */
export function mayWrite(role: WorkspaceRole): boolean {
  return atLeast(role, 'member');
}

/** Admins and the owner manage seats, and may edit or remove work they did not save. */
export function mayAdminister(role: WorkspaceRole): boolean {
  return atLeast(role, 'admin');
}

export const ROLE_LABELS: Record<WorkspaceRole, string> = {
  viewer: 'Viewer — reads shared work',
  member: 'Member — saves shared work',
  admin: 'Admin — manages seats and shared work',
  owner: 'Owner — owns the workspace',
};

/** The roles an administrator can hand out. Ownership is transferred, not granted. */
export const ASSIGNABLE_ROLES: WorkspaceRole[] = ['viewer', 'member', 'admin'];
