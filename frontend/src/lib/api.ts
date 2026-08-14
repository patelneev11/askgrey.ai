export interface TokenPair {
  access_token: string;
  refresh_token: string;
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

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}/api${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new ApiError(detail ?? `Request failed (${response.status})`, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  register: (email: string, password: string, fullName: string) =>
    request<TokenPair>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: fullName }),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  refresh: (refreshToken: string) =>
    request<TokenPair>('/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),

  me: (token: string) => request<User>('/auth/me', {}, token),

  ssoConfig: () => request<SSOConfig>('/auth/sso'),
};
