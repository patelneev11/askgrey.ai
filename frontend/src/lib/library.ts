/**
 * The saved library: results a researcher explicitly chose to keep.
 *
 * A payload here is the response body of the endpoint that produced it, so a reopened item still
 * carries its own caveats rather than any this page would add. Nothing is stored unless the
 * researcher presses save.
 */

import type { AdmetProfile, DescriptorProfile } from './screening';

/** Which output an artifact is. Mirrors the backend's closed set. */
export type ArtifactKind =
  | 'screening_profile'
  | 'screening_descriptors'
  | 'screening_admet'
  | 'screening_suggestions'
  | 'screening_patents'
  | 'regulatory_preclinical'
  | 'regulatory_ind'
  | 'grants_eligibility'
  | 'grants_budget'
  | 'grants_review_board';

/** One row of the saved list: enough to reopen an item, without its payload. */
export interface SavedArtifactSummary {
  id: string;
  kind: ArtifactKind;
  title: string;
  subtitle: string;
  /** Who saved it, and the workspace it is shared in — null when it is private to this account. */
  saved_by_user_id: string;
  workspace_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SavedArtifact<T> extends SavedArtifactSummary {
  payload: T;
}

export interface SaveArtifactRequest<T> {
  kind: ArtifactKind;
  title: string;
  subtitle?: string;
  payload: T;
}

/**
 * A screening compound profile: the two reads the tab makes of one structure, saved as one item.
 * Mirrors `ScreeningProfile` in `backend/app/services/library.py`.
 */
export interface SavedScreeningProfile {
  descriptors: DescriptorProfile;
  admet: AdmetProfile;
}

/** Short, local date for a saved-list row. */
export function savedAt(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
