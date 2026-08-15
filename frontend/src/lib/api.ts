import type { ExtractionTable } from './extraction';

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
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api${path}`, { ...init, headers, signal: controller.signal });
  } catch (cause) {
    if (controller.signal.aborted) {
      throw new TimeoutError(Math.round(timeoutMs / 1000));
    }
    throw cause;
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => formatErrorDetail(body.detail))
      .catch(() => undefined);
    throw new ApiError(detail ?? `Request failed (${response.status})`, response.status);
  }
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
};
