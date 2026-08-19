/**
 * Types mirroring `backend/app/services/protocols/`.
 *
 * Decimals cross the wire as strings (pydantic's JSON mode), so numeric quantities are typed as
 * `string` and formatted for display rather than parsed into floats — re-parsing a calculator
 * answer into a float in the browser would reintroduce exactly the error the backend's exact
 * arithmetic avoids.
 */

export type DraftOrigin = 'agent_drafted' | 'researcher_edited';

export interface ProtocolMaterial {
  name: string;
  amount: string;
  vendor_or_catalog: string;
  storage: string;
  note: string;
}

export interface ProtocolStep {
  id: string;
  order: number;
  title: string;
  instruction: string;
  duration: string;
  temperature: string;
  equipment: string[];
  critical_note: string;
}

export interface ProtocolDraft {
  title: string;
  goal: string;
  assay_type: string;
  summary: string;
  materials: ProtocolMaterial[];
  steps: ProtocolStep[];
  total_duration: string;
  expected_outcomes: string[];
  origin: DraftOrigin;
  /** "Agent-drafted content. Requires qualified researcher review before lab use." */
  disclaimer: string;
  model: string;
  drafted_at: string;
}

export interface DraftRequest {
  goal: string;
  organism_or_sample?: string;
  notes?: string;
}

export type ControlKind = 'positive' | 'negative' | 'loading' | 'specificity' | 'technical';
export type ControlStatus = 'present' | 'missing' | 'unclear';

export interface ControlFinding {
  name: string;
  kind: ControlKind;
  status: ControlStatus;
  rationale: string;
  suggested_after_step: number | null;
}

export type ChecklistCategory = 'storage' | 'spin_speed' | 'handling' | 'timing';

export interface ChecklistItem {
  id: string;
  category: ChecklistCategory;
  subject: string;
  detail: string;
  quote: string;
  step_id: string;
  step_order: number | null;
}

export interface ProtocolReview {
  assay_type: string;
  summary: string;
  controls: ControlFinding[];
  reagent_checklist: ChecklistItem[];
  missing_control_count: number;
  origin: DraftOrigin;
  disclaimer: string;
  /** Scopes the findings to controls only, so no pill can read as whole-document approval. */
  scope_note: string;
  model: string;
  reviewed_at: string;
}

export interface Quantity {
  value: string;
  unit: string;
}

export interface MasterMixComponentInput {
  name: string;
  per_reaction_volume: Quantity;
  note?: string;
}

export interface MasterMixLine {
  name: string;
  per_reaction_volume: Quantity;
  total_volume: Quantity;
  basis: string;
  note: string;
}

export interface MasterMixResult {
  kind: 'master_mix';
  reactions: number;
  replicates: number;
  overage_percent: string;
  effective_reactions: string;
  lines: MasterMixLine[];
  per_reaction_volume: Quantity;
  total_volume: Quantity;
  label: string;
  notes: string[];
}

export interface CalculationEntry {
  id: string;
  step_id?: string;
  master_mix?: {
    components: MasterMixComponentInput[];
    reactions: number;
    overage_percent?: string;
    replicates?: number;
    label?: string;
  };
}

export interface CalculationOutcome {
  id: string;
  step_id: string;
  kind: 'dilution' | 'master_mix' | 'stock_ratio' | 'solution_mass' | null;
  result: MasterMixResult | null;
  error: string | null;
}

export interface RecalculationResponse {
  outcomes: CalculationOutcome[];
}

export interface SavedProtocol {
  id: string;
  version: number;
  protocol: ProtocolDraft;
  created_at: string;
  updated_at: string;
}

/** One row of the saved-protocol list: enough to reopen it, without its payload. */
export interface SavedProtocolSummary {
  id: string;
  title: string;
  goal: string;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface ProtocolChange {
  kind: 'added' | 'removed' | 'modified' | 'reordered';
  field: string;
  label: string;
  before: string;
  after: string;
}

export interface ProtocolVersionSummary {
  version: number;
  change_summary: string;
  changes: ProtocolChange[];
  author_user_id: string;
  created_at: string;
}

export interface ProtocolHistory {
  id: string;
  current_version: number;
  versions: ProtocolVersionSummary[];
}

export interface ElnNoteBlock {
  type: 'text' | 'list_bullet' | 'list_number';
  text: string;
}

export interface ElnExportPayload {
  provider: string;
  /** "schema_ready_untested" until someone runs this against a real Benchling account. */
  integration_status: string;
  integration_note: string;
  endpoint: string;
  entry: {
    name: string;
    folderId: string;
    entryTemplateId: string | null;
    schemaId: string | null;
    customFields: Record<string, { value: string }>;
  };
  notes: ElnNoteBlock[];
  warnings: string[];
}

/** Format a backend quantity without going through a float. */
export function quantityLabel(quantity: Quantity | undefined): string {
  if (!quantity) return '—';
  const unit = quantity.unit;
  return unit === 'X' || unit === '% (w/v)'
    ? `${quantity.value}${unit}`
    : `${quantity.value} ${unit}`;
}

/** Renumber steps after a move so `order` always matches position. */
export function reorderSteps(steps: ProtocolStep[], from: number, to: number): ProtocolStep[] {
  if (to < 0 || to >= steps.length || from === to) return steps;
  const next = [...steps];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next.map((step, index) => ({ ...step, order: index + 1 }));
}

export const CONTROL_STATUS_LABEL: Record<ControlStatus, string> = {
  present: 'stated in protocol',
  missing: 'not found',
  unclear: 'not written down',
};

export const CHECKLIST_CATEGORY_LABEL: Record<ChecklistCategory, string> = {
  storage: 'Storage',
  spin_speed: 'Spin speed',
  handling: 'Handling',
  timing: 'Timing',
};
