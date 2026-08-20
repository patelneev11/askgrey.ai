import type {
  AssistantLimits,
  ChatReference,
  ChatToolSummary,
  ConversationDetail,
  ConversationSummary,
} from './chat';
import type { ExtractionTable } from './extraction';
import type {
  BoardReport,
  BudgetRequest,
  CompanyProfile,
  EligibilityReport,
  GrantBudget,
  GrantPage,
  GrantProgram,
  GrantSearchQuery,
  MatchResult,
  PersonaSummary,
  ReviewBoardRequest,
} from './grants';
import type {
  ArtifactKind,
  SaveArtifactRequest,
  SavedArtifact,
  SavedArtifactSummary,
} from './library';
import { logger } from './observability';
import { notifySessionExpired, setAccessToken } from './session';
import type {
  CalculationEntry,
  ChecklistItem,
  DraftRequest,
  ElnExportPayload,
  ProtocolDraft,
  ProtocolHistory,
  ProtocolReview,
  RecalculationResponse,
  SavedProtocol,
  SavedProtocolSummary,
} from './protocols';
import type {
  AdmetProfile,
  DescriptorProfile,
  PatentLandscape,
  SuggestionSet,
} from './screening';

export type ExportFormat = 'xlsx' | 'csv';

/** Mirrors `ExportOptions` in `backend/app/services/export/models.py`. */
export interface ExportOptions {
  include_citations?: boolean;
  include_metadata?: boolean;
  bom?: boolean;
  filename_stem?: string;
}

/** One security event from `GET /api/audit/events`, scoped by the server to the caller. */
export interface AuditEvent {
  id: string;
  occurred_at: string;
  event: string;
  kind: AuditKind;
  outcome: string;
  client_ip: string;
  /** Provenance only — which document, how many bytes, which model. Never content. */
  detail: Record<string, string | number | boolean | null>;
}

export type AuditKind = 'agent' | 'human' | 'export';

export interface AuditFeed {
  events: AuditEvent[];
  retention_days: number;
}

/** Mirrors `AccountOverview` in `backend/app/services/account.py`, scoped to the caller. */
export interface AccountOverview {
  account: {
    email: string;
    full_name: string;
    role: string;
    provider: string;
    created_at: string;
  };
  storage: {
    stored_papers: number;
    stored_bytes: number;
    retention_days: number;
    next_expiry: string | null;
  };
  saved_work: {
    counts: Record<string, number>;
    total: number;
    last_saved_at: string | null;
  };
  audit_events: number;
  sessions: { id: string; issued_at: string; expires_at: string }[];
  upstreams: { name: string; detail: string; configured: boolean }[];
  platform: {
    environment: string;
    release: string;
    llm_model: string;
    extraction_available: boolean;
    document_encryption: string;
    access_token_ttl_minutes: number;
    refresh_token_ttl_days: number;
    audit_retention_days: number;
    llm_daily_call_budget: number;
  };
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'owner' | 'admin' | 'member';
  provider: 'password' | 'oidc';
  created_at: string;
}

export interface SSOConfig {
  enabled: boolean;
  issuer: string;
  authorize_url: string | null;
}

/* ---- Regulatory tab ----
 * These mirror the pydantic models in `backend/app/services/regulatory/**`. Every response
 * carries its own `review_notice` and `requires_expert_review`, and the UI renders the notice
 * from the payload rather than from a hardcoded string, so a draft cannot be displayed without
 * the caveat that travelled with it.
 */

/** A reported number and its unit. `value` stays a string: reformatting invents precision. */
export interface Quantity {
  value: string;
  unit?: string;
}

export type Sex = 'male' | 'female' | 'both' | 'not_reported';
export type GlpStatus = 'compliant' | 'non_compliant' | 'not_reported';

export interface DoseGroup {
  label: string;
  dose?: Quantity | null;
  sex?: Sex;
  animals_per_sex?: number | null;
  notes?: string;
}

export interface StudyFinding {
  group_label?: string;
  endpoint: string;
  quantity?: Quantity | null;
  incidence?: { affected: number; examined: number } | null;
  severity?: string;
  notes?: string;
}

export interface StudyMeasurement {
  name: string;
  aliases?: string[];
  quantity?: Quantity | null;
  text_value?: string;
  notes?: string;
}

/** Mirrors `StudyTable` in `backend/app/services/regulatory/preclinical/models.py`. */
export interface StudyTable {
  study_id: string;
  title?: string;
  test_article?: string;
  species?: string;
  strain?: string;
  route?: string;
  duration?: string;
  glp_status?: GlpStatus;
  groups?: DoseGroup[];
  findings?: StudyFinding[];
  measurements?: StudyMeasurement[];
}

export type DiscrepancyKind =
  'contradicted_value' | 'unsupported_number' | 'unit_mismatch' | 'rounded_value';

export interface Discrepancy {
  kind: DiscrepancyKind;
  severity: 'critical' | 'warning' | 'info';
  section: string;
  narrative_value: string;
  source_value: string;
  source_label: string;
  context: string;
  start_char: number;
  end_char: number;
  explanation: string;
}

export interface NarrativeSection {
  key: string;
  heading: string;
  text: string;
  draft_status: string;
  gaps: string[];
  requires_expert_review: boolean;
  review_notice: string;
}

export interface PreclinicalReport {
  study_id: string;
  generated_at: string;
  sections: NarrativeSection[];
  discrepancies: Discrepancy[];
  audit: {
    auditor_version: string;
    method: string;
    numbers_checked: number;
    numbers_matched: number;
    numbers_flagged: number;
    source_values: number;
  };
  requires_expert_review: boolean;
  review_notice: string;
  /** What wrote the narrative. */
  drafter: string;
  /**
   * True only for the backend's development-only fixture drafter, whose narrative contains
   * deliberately wrong numbers so the audit's flagged view can be exercised. The UI must say so
   * rather than presenting fixture output as a draft.
   */
  fixture_draft: boolean;
}

export type EvidenceKind =
  | 'substance_identity'
  | 'manufacturing_site'
  | 'manufacturing_step'
  | 'material_control'
  | 'specification'
  | 'analytical_method'
  | 'assay_result'
  | 'batch'
  | 'impurity'
  | 'stability_result'
  | 'reference_standard'
  | 'container_closure'
  | 'formulation'
  | 'nonclinical_study';

export interface EvidenceRecord {
  kind: EvidenceKind;
  label: string;
  value?: string;
  unit?: string;
  batch_id?: string;
  method?: string;
  acceptance_criterion?: string;
  study_id?: string;
  section_id?: string;
  detail?: string;
}

export interface IndDraftRequest {
  program_name: string;
  substance_name?: string;
  dosage_form?: string;
  section_ids: string[];
  evidence: EvidenceRecord[];
}

export interface ReferenceInfo {
  version: string;
  retrieved: string;
  sources: {
    id: string;
    title: string;
    url: string;
    document_date: string;
    covers: string;
  }[];
  notes: string[];
}

export type GapKind =
  'no_evidence_submitted' | 'missing_evidence_kind' | 'author_must_supply' | 'drafter_reported';

export interface Gap {
  kind: GapKind;
  description: string;
  evidence_kind: EvidenceKind | null;
}

export interface IndSection {
  section_id: string;
  title: string;
  module: string;
  status: 'drafted' | 'drafted_with_gaps' | 'not_drafted';
  text: string;
  gaps: Gap[];
  evidence_used: string[];
  requires_expert_completion: boolean;
  requires_expert_review: boolean;
  review_notice: string;
  source_reference: string;
}

export interface IndDraft {
  program_name: string;
  generated_at: string;
  sections: IndSection[];
  unknown_section_ids: string[];
  unused_evidence: string[];
  reference: ReferenceInfo;
  requires_expert_review: boolean;
  review_notice: string;
}

export interface IndStructure {
  reference: ReferenceInfo;
  sections: {
    id: string;
    module: string;
    title: string;
    requires: EvidenceKind[];
    draftable: boolean;
  }[];
  requires_expert_review: boolean;
  review_notice: string;
}

export type Jurisdiction = 'fda' | 'ema' | 'pmda';

export interface RequirementFinding {
  requirement_id: string;
  title: string;
  ctd_sections: string[];
  matched_scope: string;
  citation: { document: string; url: string; document_date: string };
  expectation: string;
  status: 'addressed' | 'missing' | 'indeterminate';
  explanation: string;
}

/**
 * How old the shipped guideline snapshot is, computed by the backend from its `retrieved` date.
 *
 * `status` is a statement about when a human last read the source documents, not about whether the
 * encoded expectations are complete or legally in force.
 */
export interface SnapshotFreshness {
  version: string;
  retrieved: string;
  age_days: number;
  review_interval_days: number;
  stale_after_days: number;
  review_due_on: string;
  stale_on: string;
  status: 'current' | 'review_due' | 'stale';
  message: string;
  update_procedure: string;
}

export interface GuidelineCheckReport {
  section_id: string;
  word_count: number;
  min_words_to_judge: number;
  jurisdictions: {
    jurisdiction: Jurisdiction;
    version: string;
    retrieved: string;
    freshness: SnapshotFreshness;
    findings: RequirementFinding[];
    out_of_scope_requirement_ids: string[];
  }[];
  /** The worst-aged snapshot behind the report, or null when nothing was compared. */
  snapshot: SnapshotFreshness | null;
  requires_expert_review: boolean;
  review_notice: string;
  limitations: string;
}

export interface GuidelineReference {
  jurisdictions: {
    jurisdiction: Jurisdiction;
    version: string;
    retrieved: string;
    freshness: SnapshotFreshness;
    notes: string;
    requirements: {
      id: string;
      title: string;
      ctd_sections: string[];
      citation: { document: string; url: string; document_date: string };
      expectation: string;
    }[];
  }[];
  snapshot: SnapshotFreshness | null;
  requires_expert_review: boolean;
  review_notice: string;
  limitations: string;
}

const API_BASE = import.meta.env.VITE_API_URL ?? '';

/** Mirrors `CapabilityReport` in `backend/app/api/system.py`. */
export interface Capabilities {
  extraction_available: boolean;
}

/** Mirrors `WorkspaceSource` in `backend/app/schemas/literature.py`. */
export interface StoredSource {
  id: string;
  label: string;
  kind: 'upload' | 'url';
  url: string;
  document_id: string;
}

export interface StoredWorkspace {
  goal: string;
  sources: StoredSource[];
  table: ExtractionTable | null;
  updated_at?: string | null;
  stored_document_ids?: string[];
}

/**
 * A hung backend is indistinguishable from a slow one without a bound, so every request gets
 * one. Extraction runs a full LLM pass per paper, hence the far longer allowance there.
 */
const DEFAULT_TIMEOUT_MS = 30_000;
const EXTRACTION_TIMEOUT_MS = 180_000;
// Drafting and control review each run a full model pass over a whole protocol.
const DRAFT_TIMEOUT_MS = 120_000;
const REGULATORY_DRAFT_TIMEOUT_MS = 180_000;
const SUGGESTION_TIMEOUT_MS = 60_000;
// The patent route talks to USPTO, which retries upstream before giving up.
const PATENT_SEARCH_TIMEOUT_MS = 45_000;
/** Semantic matching is one LLM pass over a page of opportunities, not a full paper. */
const LLM_TIMEOUT_MS = 120_000;
/** How long to wait for a turn's first byte; the stream itself is then unbounded by design. */
const CHAT_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /**
     * The `detail` the API itself sent, when it sent one. A status with no detail came from
     * something between the browser and the API — a dev proxy, a load balancer — so a caller
     * that wants to explain the failure in its own words can tell the two apart.
     */
    readonly detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ValidationIssue {
  msg?: string;
}

/**
 * FastAPI sends `detail` as a string for raised HTTPExceptions but as a list of pydantic
 * issue objects for 422 responses, so both shapes have to survive the trip to the UI.
 */
export function formatErrorDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = (detail as ValidationIssue[])
      .map((issue) => issue?.msg)
      .filter((msg): msg is string => typeof msg === 'string' && msg.length > 0);
    return messages.length > 0 ? messages.join('. ') : undefined;
  }
  return undefined;
}

export class TimeoutError extends ApiError {
  constructor(seconds: number) {
    super(`The server did not respond within ${seconds}s. It may be busy — try again.`, 408);
    this.name = 'TimeoutError';
  }
}

async function send(
  path: string,
  init: RequestInit,
  token?: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
  renewable = true,
): Promise<Response> {
  const headers = new Headers(init.headers);
  // FormData bodies must keep the boundary the browser generates for them.
  if (!(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // The query string carries the researcher's question; only the route is loggable.
  const route = path.split('?')[0];
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api${path}`, { ...init, headers, signal: controller.signal });
  } catch (cause) {
    if (controller.signal.aborted) {
      logger.warn('api.timeout', { route, timeout_ms: timeoutMs });
      throw new TimeoutError(Math.round(timeoutMs / 1000));
    }
    logger.error('api.unreachable', cause, { route });
    throw cause;
  } finally {
    clearTimeout(timer);
  }
  const durationMs = Math.round(performance.now() - started);
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => formatErrorDetail(body.detail))
      .catch(() => undefined);
    // 401 during session restore is the normal "not signed in" path, not a defect.
    const level = response.status === 401 ? logger.info : logger.warn;
    level('api.error', {
      route,
      status: response.status,
      duration_ms: durationMs,
      request_id: response.headers.get('X-Request-ID'),
    });
    if (response.status === 401 && renewable && token && !path.startsWith('/auth/')) {
      return renew(path, init, timeoutMs);
    }
    throw new ApiError(detail ?? `Request failed (${response.status})`, response.status, detail);
  }
  logger.debug('api.ok', { route, duration_ms: durationMs });
  return response;
}

/**
 * Swap an expired access token for a fresh one and run the request again.
 *
 * The access token lives in memory for 30 minutes and was previously only minted at page
 * load, so a user who spent longer than that reading papers and writing a goal got
 * "Not authenticated" from every call — most visibly from an upload — while the app still
 * showed them signed in. `renewable` is false on the retry, so a still-401 reply ends here.
 */
async function renew(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  let renewed: TokenResponse;
  try {
    renewed = await refresh();
  } catch {
    // The refresh cookie is gone or revoked too: this session is over, say so rather than
    // leaving the user clicking a dead workspace.
    notifySessionExpired();
    throw new ApiError('Your session expired. Sign in again to continue.', 401);
  }
  setAccessToken(renewed.access_token);
  return send(path, init, renewed.access_token, timeoutMs, false);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
  timeoutMs?: number,
): Promise<T> {
  const response = await send(path, init, token, timeoutMs);
  return (await response.json()) as T;
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

/** RFC 6266: the percent-encoded `filename*` wins over the ASCII fallback when present. */
export function parseFilename(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // A malformed header should never cost the user their download.
    }
  }
  const plain = /filename="([^"]+)"/i.exec(disposition);
  return plain ? plain[1] : fallback;
}

async function download(
  path: string,
  init: RequestInit,
  token: string | undefined,
  fallbackName: string,
): Promise<DownloadedFile> {
  const response = await send(path, init, token);
  return {
    blob: await response.blob(),
    filename: parseFilename(response.headers.get('Content-Disposition'), fallbackName),
  };
}

// Refresh tokens rotate on use, so the server treats a replayed one as theft and revokes the
// session. Two overlapping refreshes are therefore never two requests: they share one.
let refreshing: Promise<TokenResponse> | null = null;

function refresh(): Promise<TokenResponse> {
  if (!refreshing) {
    refreshing = request<TokenResponse>('/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    }).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export const api = {
  // `credentials: 'include'` is what carries the HttpOnly refresh cookie; without it the
  // browser drops the cookie on a cross-origin call and every reload signs the user out.
  register: (email: string, password: string, fullName: string) =>
    request<TokenResponse>('/auth/register', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ email, password, full_name: fullName }),
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    }),

  refresh,

  logout: () => send('/auth/logout', { method: 'POST', credentials: 'include' }),

  /** Revoke every refresh session this account holds, not just this browser's. */
  logoutAll: (token?: string) =>
    send('/auth/logout-all', { method: 'POST', credentials: 'include' }, token),

  me: (token: string) => request<User>('/auth/me', {}, token),

  ssoConfig: () => request<SSOConfig>('/auth/sso'),

  /** Extract the goal's fields out of an uploaded PDF (Ticket 1.4). */
  extractFromUpload: (file: File, goal: string, token?: string) => {
    const body = new FormData();
    body.append('file', file);
    body.append('goal', goal);
    return request<ExtractionTable>(
      '/pdf-extraction/upload',
      { method: 'POST', body },
      token,
      EXTRACTION_TIMEOUT_MS,
    );
  },

  /** Extract from a PMC article or direct PDF link (Ticket 1.4). */
  extractFromUrl: (url: string, goal: string, token?: string) =>
    request<ExtractionTable>(
      '/pdf-extraction/url',
      { method: 'POST', body: JSON.stringify({ url, goal }) },
      token,
      EXTRACTION_TIMEOUT_MS,
    ),

  /** Extract again from a paper the server already holds, after a reload lost its bytes. */
  extractFromStoredDocument: (documentId: string, goal: string, token?: string) =>
    request<ExtractionTable>(
      `/pdf-extraction/documents/${encodeURIComponent(documentId)}`,
      { method: 'POST', body: JSON.stringify({ goal }) },
      token,
      EXTRACTION_TIMEOUT_MS,
    ),

  /** What the deployment can actually do — extraction needs model credentials server-side. */
  capabilities: (token?: string) => request<Capabilities>('/status/capabilities', {}, token),

  /** The saved Literature workspace for the signed-in user. */
  loadWorkspace: (token?: string) => request<StoredWorkspace>('/literature/workspace', {}, token),

  saveWorkspace: (workspace: StoredWorkspace, token?: string) =>
    request<StoredWorkspace>(
      '/literature/workspace',
      { method: 'PUT', body: JSON.stringify(workspace) },
      token,
    ),

  /**
   * The bytes of a stored paper, so a citation from a linked paper renders a real page.
   *
   * The document id is a digest the backend issued; nothing here can ask it for a URL.
   */
  documentPdf: async (documentId: string, token?: string) => {
    const response = await send(
      `/literature/documents/${encodeURIComponent(documentId)}/pdf`,
      {},
      token,
    );
    return response.blob();
  },

  /** Delete one stored paper. A paper stored by another account is a 404, not a deletion. */
  deleteDocument: (documentId: string, token?: string) =>
    send(`/literature/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' }, token),

  /** This account's own identity, storage, saved work, sessions and deployment configuration. */
  accountOverview: (token?: string) =>
    request<AccountOverview>('/account/overview', {}, token),

  /** This account's own security events, newest first. There is no parameter for whose. */
  auditEvents: (kind?: AuditKind, token?: string) =>
    request<AuditFeed>(`/audit/events${kind ? `?kind=${kind}` : ''}`, {}, token),

  /** Deterministic RDKit descriptors and drug-likeness rule sets for one structure. */
  screeningDescriptors: (smiles: string, token?: string) =>
    request<DescriptorProfile>(
      '/screening/sar/descriptors',
      { method: 'POST', body: JSON.stringify({ smiles }) },
      token,
    ),

  /** ADMET classifications from published physicochemical rules, each with its model basis. */
  screeningAdmet: (smiles: string, token?: string) =>
    request<AdmetProfile>(
      '/screening/admet',
      { method: 'POST', body: JSON.stringify({ smiles }) },
      token,
    ),

  /** Heuristic substituent suggestions. LLM-backed, so it gets the longer allowance. */
  screeningSuggestions: (smiles: string, token?: string) =>
    request<SuggestionSet>(
      '/screening/sar/suggestions',
      { method: 'POST', body: JSON.stringify({ smiles }) },
      token,
      SUGGESTION_TIMEOUT_MS,
    ),

  /**
   * Keyword prior-art search over USPTO patent applications.
   *
   * Calls an external API, so it gets the longer allowance. Only the structure and keywords are
   * sent: the endpoint takes no URL, and the upstream host is fixed server-side.
   */
  screeningPatents: (smiles: string, keywords: string, token?: string) =>
    request<PatentLandscape>(
      '/screening/patents/search',
      { method: 'POST', body: JSON.stringify({ smiles, keywords }) },
      token,
      PATENT_SEARCH_TIMEOUT_MS,
    ),

  /** Render the review table as a workbook or CSV and hand back the file (Ticket 1.5). */
  exportTable: (
    table: ExtractionTable,
    format: ExportFormat,
    options: ExportOptions = {},
    token?: string,
  ) =>
    download(
      `/export/${format}`,
      { method: 'POST', body: JSON.stringify({ table, options }) },
      token,
      `review-table.${format}`,
    ),

  /** Draft a protocol from a natural-language goal. LLM-backed and rate-limited server-side. */
  draftProtocol: (body: DraftRequest, token?: string) =>
    request<ProtocolDraft>(
      '/protocols/draft',
      { method: 'POST', body: JSON.stringify(body) },
      token,
      DRAFT_TIMEOUT_MS,
    ),

  /** Agent-drafted control findings plus the extracted reagent checklist. */
  reviewControls: (protocol: ProtocolDraft, token?: string) =>
    request<ProtocolReview>(
      '/protocols/controls/review',
      { method: 'POST', body: JSON.stringify({ protocol }) },
      token,
      DRAFT_TIMEOUT_MS,
    ),

  /** Deterministic extraction; available even when no model is configured. */
  reagentChecklist: (protocol: ProtocolDraft, token?: string) =>
    request<ChecklistItem[]>(
      '/protocols/checklist',
      { method: 'POST', body: JSON.stringify({ protocol }) },
      token,
    ),

  /** Recalculate every inline calculator field in one batch; pure arithmetic, no model. */
  recalculate: (entries: CalculationEntry[], batchScale: number | null, token?: string) =>
    request<RecalculationResponse>(
      '/protocols/calculator/recalculate',
      { method: 'POST', body: JSON.stringify({ entries, batch_scale: batchScale }) },
      token,
    ),

  saveProtocol: (protocol: ProtocolDraft, changeSummary: string, token?: string) =>
    request<SavedProtocol>(
      '/protocols',
      { method: 'POST', body: JSON.stringify({ protocol, change_summary: changeSummary }) },
      token,
    ),

  updateProtocol: (id: string, protocol: ProtocolDraft, changeSummary: string, token?: string) =>
    request<SavedProtocol>(
      `/protocols/${encodeURIComponent(id)}`,
      { method: 'PUT', body: JSON.stringify({ protocol, change_summary: changeSummary }) },
      token,
    ),

  /** The caller's saved protocols, so a save is reachable again after a reload. */
  listProtocols: (token?: string) => request<SavedProtocolSummary[]>('/protocols', {}, token),

  loadProtocol: (id: string, token?: string) =>
    request<SavedProtocol>(`/protocols/${encodeURIComponent(id)}`, {}, token),

  protocolHistory: (id: string, token?: string) =>
    request<ProtocolHistory>(`/protocols/${encodeURIComponent(id)}/history`, {}, token),

  /**
   * Keep one result in the saved library.
   *
   * Called only when the researcher asks to save: the backend re-validates the payload against the
   * model that produced it, so a stored result keeps the caveats it was shown with.
   */
  saveArtifact: <T>(request_: SaveArtifactRequest<T>, token?: string) =>
    request<SavedArtifact<T>>(
      '/library',
      { method: 'POST', body: JSON.stringify(request_) },
      token,
    ),

  /** Saved items of one kind, or every kind when none is named. */
  listArtifacts: (kind?: ArtifactKind, token?: string) =>
    request<SavedArtifactSummary[]>(
      kind ? `/library?kind=${encodeURIComponent(kind)}` : '/library',
      {},
      token,
    ),

  loadArtifact: <T>(id: string, token?: string) =>
    request<SavedArtifact<T>>(`/library/${encodeURIComponent(id)}`, {}, token),

  deleteArtifact: (id: string, token?: string) =>
    send(`/library/${encodeURIComponent(id)}`, { method: 'DELETE' }, token),

  /**
   * Build the Benchling entry payload for a protocol.
   *
   * Schema-ready and untested against a live Benchling account: the response carries
   * `integration_status`, which the UI must surface rather than presenting this as a real export.
   */
  exportEln: (protocol: ProtocolDraft, folderId: string, token?: string) =>
    request<ElnExportPayload>(
      '/protocols/export/eln',
      { method: 'POST', body: JSON.stringify({ protocol, folder_id: folderId }) },
      token,
    ),

  /**
   * Draft a preclinical narrative and audit its numbers against the submitted table.
   *
   * The same long allowance as extraction: this is a full LLM pass followed by a
   * deterministic audit, and a 30s bound would time out a legitimate run.
   */
  preclinicalReport: (table: StudyTable, token?: string) =>
    request<PreclinicalReport>(
      '/regulatory/preclinical/report',
      { method: 'POST', body: JSON.stringify(table) },
      token,
      REGULATORY_DRAFT_TIMEOUT_MS,
    ),

  /** The dated CTD heading tree the IND drafter works against. */
  indStructure: (token?: string) => request<IndStructure>('/regulatory/ind/structure', {}, token),

  indDraft: (body: IndDraftRequest, token?: string) =>
    request<IndDraft>(
      '/regulatory/ind/draft',
      { method: 'POST', body: JSON.stringify(body) },
      token,
      REGULATORY_DRAFT_TIMEOUT_MS,
    ),

  /** Deterministic keyword-signal comparison, so the default timeout is ample. */
  guidelineCheck: (
    body: {
      section_id: string;
      draft_text: string;
      jurisdictions: Jurisdiction[];
    },
    token?: string,
  ) =>
    request<GuidelineCheckReport>(
      '/regulatory/guidelines/check',
      { method: 'POST', body: JSON.stringify(body) },
      token,
    ),

  guidelineReference: (token?: string) =>
    request<GuidelineReference>('/regulatory/guidelines/reference', {}, token),

  /** Filtered opportunity search across the enabled providers (Ticket 4.1). */
  searchGrants: (query: GrantSearchQuery, token?: string) => {
    const params = new URLSearchParams();
    if (query.keyword.trim()) params.set('keyword', query.keyword.trim());
    if (query.agency.trim()) params.set('agency', query.agency.trim());
    if (query.program) params.set('program', query.program);
    if (query.closing_before) params.set('closing_before', query.closing_before);
    params.set('open_only', String(query.open_only));
    return request<GrantPage>(`/grants/search?${params.toString()}`, {}, token);
  },

  /** Rank the same search by how well each topic matches a research focus (LLM-backed). */
  matchGrants: (focus: string, query: GrantSearchQuery, token?: string) =>
    request<MatchResult>(
      '/grants/match',
      {
        method: 'POST',
        body: JSON.stringify({
          focus,
          keyword: query.keyword.trim(),
          agency: query.agency.trim(),
          program: query.program || null,
          open_only: query.open_only,
          closing_before: query.closing_before || null,
        }),
      },
      token,
      LLM_TIMEOUT_MS,
    ),

  /** Deterministic SBIR/STTR eligibility screen against the editable rule set (Ticket 4.2). */
  checkEligibility: (profile: CompanyProfile, program: GrantProgram, token?: string) =>
    request<EligibilityReport>(
      '/grants/eligibility',
      { method: 'POST', body: JSON.stringify({ profile, program }) },
      token,
    ),

  /** Cost line items into SF-424 (R&R) shape under the configured federal rules (Ticket 4.3). */
  buildBudget: (budget: BudgetRequest, token?: string) =>
    request<GrantBudget>(
      '/grants/budget',
      { method: 'POST', body: JSON.stringify(budget) },
      token,
    ),

  /** The same budget as a file, rendered by the shared exporter. */
  exportBudget: (budget: BudgetRequest, format: ExportFormat, token?: string) =>
    download(
      `/grants/budget/export?format=${format}`,
      { method: 'POST', body: JSON.stringify(budget) },
      token,
      `grant-budget.${format}`,
    ),

  reviewPersonas: (token?: string) =>
    request<PersonaSummary[]>('/grants/review-board/personas', {}, token),

  /** What the assistant can actually do, so the tab states it rather than implying it. */
  chatTools: (token?: string) => request<ChatToolSummary[]>('/chat/tools', {}, token),

  /** What it will answer and what this account has left to spend on it. */
  chatLimits: (token?: string) => request<AssistantLimits>('/chat/limits', {}, token),

  startConversation: (token?: string) =>
    request<ConversationSummary>('/chat/conversations', { method: 'POST', body: '{}' }, token),

  listConversations: (token?: string) =>
    request<ConversationSummary[]>('/chat/conversations', {}, token),

  loadConversation: (id: string, token?: string) =>
    request<ConversationDetail>(`/chat/conversations/${encodeURIComponent(id)}`, {}, token),

  deleteConversation: (id: string, token?: string) =>
    send(`/chat/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }, token),

  /**
   * Ask one question and read the answer as it is written.
   *
   * The response body is a server-sent event stream, so this hands back the body rather than
   * parsed JSON. The timeout bounds the wait for the first byte only — `send` clears it once the
   * headers arrive, which is what lets a long tool-using turn finish.
   */
  sendChatMessage: async (
    conversationId: string,
    message: string,
    references: ChatReference[],
    token?: string,
  ) => {
    const response = await send(
      `/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: 'POST', body: JSON.stringify({ message, references }) },
      token,
      CHAT_TIMEOUT_MS,
    );
    if (!response.body) {
      throw new ApiError('The assistant sent no reply stream.', 502);
    }
    return response.body;
  },

  reviewSection: (review: ReviewBoardRequest, token?: string) =>
    request<BoardReport>(
      '/grants/review-board',
      { method: 'POST', body: JSON.stringify(review) },
      token,
      LLM_TIMEOUT_MS,
    ),
};

