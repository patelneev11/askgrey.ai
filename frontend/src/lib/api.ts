import type { ExtractionTable } from './extraction';
import { logger } from './observability';
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

const API_BASE = import.meta.env.VITE_API_URL ?? '';

/**
 * A hung backend is indistinguishable from a slow one without a bound, so every request gets
 * one. Extraction runs a full LLM pass per paper, hence the far longer allowance there.
 */
const DEFAULT_TIMEOUT_MS = 30_000;
const EXTRACTION_TIMEOUT_MS = 180_000;
// Drafting and control review each run a full model pass over a whole protocol.
const DRAFT_TIMEOUT_MS = 120_000;
const SUGGESTION_TIMEOUT_MS = 60_000;
// The patent route talks to USPTO, which retries upstream before giving up.
const PATENT_SEARCH_TIMEOUT_MS = 45_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
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
    throw new ApiError(detail ?? `Request failed (${response.status})`, response.status);
  }
  logger.debug('api.ok', { route, duration_ms: durationMs });
  return response;
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

  refresh: () =>
    request<TokenResponse>('/auth/refresh', { method: 'POST', credentials: 'include' }),

  logout: () => send('/auth/logout', { method: 'POST', credentials: 'include' }),

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

  protocolHistory: (id: string, token?: string) =>
    request<ProtocolHistory>(`/protocols/${encodeURIComponent(id)}/history`, {}, token),

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
};

