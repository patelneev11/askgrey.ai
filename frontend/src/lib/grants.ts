/**
 * The Grants wire types, mirroring `backend/app/services/grants`.
 *
 * Money and score fields arrive as strings where the backend holds them as `Decimal`: the
 * amounts are already rounded to cents there, and re-parsing them into a float client-side
 * would reintroduce the error the backend went to trouble to avoid. They are displayed, not
 * recomputed.
 */

export type GrantSource = 'grants_gov' | 'sbir';
export type GrantProgram = 'SBIR' | 'STTR' | 'BOTH' | 'OTHER';
export type GrantStatus = 'open' | 'forecasted' | 'closed';
/** Whether the provider published the set-aside program or it was read out of the title text. */
export type ProgramProvenance = 'stated' | 'inferred';

export interface GrantOpportunity {
  source: GrantSource;
  opportunity_id: string;
  number: string;
  title: string;
  agency: string;
  agency_code: string;
  branch: string;
  program: GrantProgram | null;
  program_provenance: ProgramProvenance | null;
  status: GrantStatus | null;
  posted_date: string | null;
  close_date: string | null;
  funding_ceiling: number | null;
  funding_floor: number | null;
  topic_description: string;
  topics: string[];
  url: string;
}

/** Per-provider outcome for one search: one provider being down must not hide the other. */
export interface SourceStatus {
  source: GrantSource;
  ok: boolean;
  total_count: number;
  returned: number;
  error: string;
}

export interface GrantSearchQuery {
  keyword: string;
  agency: string;
  program: GrantProgram | '';
  open_only: boolean;
  closing_before: string;
}

export interface GrantPage {
  opportunities: GrantOpportunity[];
  total_count: number;
  page: number;
  page_size: number;
  sources: SourceStatus[];
}

export interface OpportunityMatch {
  opportunity: GrantOpportunity;
  score: number;
  rationale: string;
  matched_terms: string[];
}

export interface MatchResult {
  focus: string;
  matcher: string;
  candidates_considered: number;
  matches: OpportunityMatch[];
  sources: SourceStatus[];
}

export type Verdict = 'pass' | 'fail' | 'needs_review';

export interface Ownership {
  us_individuals_percent: number | null;
  other_small_businesses_percent: number | null;
  investment_companies_percent: number | null;
  foreign_percent: number | null;
}

export type OrganizationType =
  | 'for_profit'
  | 'nonprofit'
  | 'academic'
  | 'government'
  | 'individual';
export type AwardPhase = 'phase_i' | 'phase_ii' | 'direct_phase_ii';
export type PiEmployer = 'company' | 'research_institution' | 'other';

/** `null` means "not recorded" and produces `needs_review`; it is never treated as zero. */
export interface CompanyProfile {
  name: string;
  organization_type: OrganizationType | null;
  principal_place_of_business_us: boolean | null;
  employee_count: number | null;
  ownership: Ownership;
  pi_primary_employer: PiEmployer | null;
  pi_company_time_percent: number | null;
  has_research_institution_partner: boolean | null;
  work_by_company_percent: number | null;
  work_by_research_institution_percent: number | null;
  phase: AwardPhase | null;
  prior_phase_i_award_same_topic: boolean | null;
  phase_i_awards_last_five_years: number | null;
  phase_ii_awards_last_five_years: number | null;
  sam_registered: boolean | null;
  sba_company_registry_registered: boolean | null;
  research_focus: string;
}

export interface RuleOutcome {
  rule_id: string;
  title: string;
  verdict: Verdict;
  explanation: string;
  citation: string;
  missing_fields: string[];
}

export interface EligibilityReport {
  program: GrantProgram;
  phase: AwardPhase | null;
  config_version: string;
  outcomes: RuleOutcome[];
  verdict: Verdict;
  summary: string;
}

export type CostCategory =
  | 'equipment'
  | 'travel'
  | 'participant_support'
  | 'materials'
  | 'consultant'
  | 'subaward'
  | 'other';

export interface PersonnelLine {
  role: string;
  name: string;
  key_person: boolean;
  base_salary_annual: string;
  effort_percent: string;
  months: string;
  fringe_rate_percent: string | null;
}

export interface CostLine {
  category: CostCategory;
  description: string;
  quantity: string;
  unit_cost: string;
}

export interface BudgetRequest {
  program: GrantProgram;
  phase: AwardPhase;
  period_months: number;
  organization: string;
  project_title: string;
  personnel: PersonnelLine[];
  costs: CostLine[];
  indirect_rate_percent: string | null;
  fee_percent: string | null;
}

export interface BudgetLine {
  label: string;
  basis: string;
  amount: string;
  category: CostCategory | null;
}

export interface BudgetSection {
  code: string;
  title: string;
  lines: BudgetLine[];
  subtotal: string;
}

export interface Adjustment {
  rule_id: string;
  message: string;
  amount: string;
  authority: string;
}

export interface GrantBudget {
  program: GrantProgram;
  phase: AwardPhase;
  period_months: number;
  organization: string;
  project_title: string;
  rules_version: string;
  sections: BudgetSection[];
  indirect_base: string;
  indirect_rate_percent: string;
  fee_percent: string;
  adjustments: Adjustment[];
  warnings: string[];
  total_direct: string;
  indirect: string;
  total_direct_and_indirect: string;
  fee: string;
  total: string;
}

/* ---- Mock review board (POST /grants/review-board) ---- */

/** The board's own bounds, mirrored so the form can say what it needs before a 422 does. */
export const MIN_SECTION_CHARS = 200;
export const MAX_SECTION_CHARS = 20_000;

export interface PersonaSummary {
  id: string;
  name: string;
  focus: string;
  criteria: string[];
}

export interface CriterionScore {
  criterion: string;
  /** NIH scale: 1 is exceptional, 9 is poor, so lower is better. Never rescaled here. */
  score: number;
  reasoning: string;
}

export interface PersonaReview {
  persona_id: string;
  persona_name: string;
  focus: string;
  scores: CriterionScore[];
  overall_score: number;
  strengths: string[];
  weaknesses: string[];
  comment: string;
}

export interface BoardReport {
  section_name: string;
  program: string | null;
  phase: string | null;
  config_version: string;
  validation_status: 'unvalidated';
  caveat: string;
  model: string;
  reviews: PersonaReview[];
  summary: string;
}

export interface ReviewBoardRequest {
  section_name: string;
  program: string;
  phase: string;
  text: string;
  personas: string[];
}

export const EMPTY_PROFILE: CompanyProfile = {
  name: '',
  organization_type: null,
  principal_place_of_business_us: null,
  employee_count: null,
  ownership: {
    us_individuals_percent: null,
    other_small_businesses_percent: null,
    investment_companies_percent: null,
    foreign_percent: null,
  },
  pi_primary_employer: null,
  pi_company_time_percent: null,
  has_research_institution_partner: null,
  work_by_company_percent: null,
  work_by_research_institution_percent: null,
  phase: null,
  prior_phase_i_award_same_topic: null,
  phase_i_awards_last_five_years: null,
  phase_ii_awards_last_five_years: null,
  sam_registered: null,
  sba_company_registry_registered: null,
  research_focus: '',
};

export const SOURCE_LABELS: Record<GrantSource, string> = {
  grants_gov: 'grants.gov',
  sbir: 'SBIR.gov',
};

export const VERDICT_LABELS: Record<Verdict, string> = {
  pass: 'Pass',
  fail: 'Fail',
  needs_review: 'Needs review',
};

/** The provider states a deadline or it does not; never invent one to fill the field. */
export function deadlineLabel(opportunity: GrantOpportunity): string {
  return opportunity.close_date ?? 'No published deadline';
}

/**
 * The set-aside program plus how it was determined.
 *
 * grants.gov publishes no set-aside field, so a program there is a keyword read of the title and
 * synopsis and must not be shown as if the agency stated it.
 */
export function programLabel(opportunity: GrantOpportunity): string {
  if (opportunity.program === null) return 'Not stated';
  return opportunity.program_provenance === 'inferred'
    ? `${opportunity.program} (inferred from title)`
    : opportunity.program;
}

export function fundingLabel(opportunity: GrantOpportunity): string {
  return opportunity.funding_ceiling === null
    ? 'Not stated'
    : `$${opportunity.funding_ceiling.toLocaleString('en-US')}`;
}

/** Days until close, `null` when the provider published no deadline. */
export function daysUntilClose(opportunity: GrantOpportunity, today: Date = new Date()): number | null {
  if (!opportunity.close_date) return null;
  const close = new Date(`${opportunity.close_date}T00:00:00Z`);
  if (Number.isNaN(close.getTime())) return null;
  const start = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((close.getTime() - start) / 86_400_000);
}

/** Formats a wire `Decimal` string for display without re-deriving it. */
export function money(amount: string): string {
  const value = Number(amount);
  if (Number.isNaN(value)) return amount;
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  });
}
