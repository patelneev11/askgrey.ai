import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import { AuthProvider } from '@/lib/auth';

import { LoginPage } from './LoginPage';

const terms = vi.fn();
const ssoConfig = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      terms: (...args: unknown[]) => terms(...args),
      ssoConfig: (...args: unknown[]) => ssoConfig(...args),
      login: vi.fn(),
      register: vi.fn(),
      me: vi.fn(),
      refresh: () => Promise.reject(new Error('no session')),
    },
  };
});

beforeEach(() => {
  terms.mockReset();
  ssoConfig.mockReset();
  terms.mockResolvedValue({ version: '2026-09-08' });
});

function renderLogin(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('offers Google only when the deployment has credentials for it', async () => {
  ssoConfig.mockResolvedValue({
    enabled: false,
    issuer: '',
    authorize_url: null,
    google_enabled: false,
  });
  renderLogin();

  await screen.findByRole('button', { name: /sign in/i });
  expect(screen.queryByRole('link', { name: /continue with google/i })).toBeNull();
});

it('sends the Google button at the server-side start route, never at Google directly', async () => {
  ssoConfig.mockResolvedValue({
    enabled: false,
    issuer: '',
    authorize_url: null,
    google_enabled: true,
  });
  renderLogin();

  const link = await screen.findByRole('link', { name: /continue with google/i });
  // The client id and the secret stay on the server: the browser only ever sees our own path.
  expect(link).toHaveAttribute('href', '/api/auth/google/start');
});

it('shows what went wrong when Google sends the visitor back with an error', async () => {
  ssoConfig.mockResolvedValue({
    enabled: false,
    issuer: '',
    authorize_url: null,
    google_enabled: true,
  });
  renderLogin('/login?sso_error=Google%20has%20not%20verified%20that%20email%20address');

  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent(/has not verified that email address/i),
  );
});
