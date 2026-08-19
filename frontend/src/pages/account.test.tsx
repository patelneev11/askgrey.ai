import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AccountOverview } from '@/lib/api';
import { OnboardingProvider } from '@/lib/onboarding';
import { onSessionExpired, setAccessToken } from '@/lib/session';

import { SettingsPage } from './SettingsPage';
import { WorkspacePage } from './WorkspacePage';

const accountOverview = vi.fn();
const logoutAll = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      accountOverview: (...args: unknown[]) => accountOverview(...args),
      logoutAll: (...args: unknown[]) => logoutAll(...args),
    },
  };
});

function overview(overrides: Partial<AccountOverview> = {}): AccountOverview {
  return {
    account: {
      email: 'chemist@askgrey.ai',
      full_name: 'Dana Okoye',
      role: 'owner',
      provider: 'password',
      created_at: '2026-02-02T10:00:00+00:00',
    },
    storage: {
      stored_papers: 3,
      stored_bytes: 4_200_000,
      retention_days: 90,
      next_expiry: new Date(Date.now() + 45 * 86_400_000).toISOString(),
    },
    saved_work: {
      counts: { screening_profile: 2, grants_budget: 1 },
      total: 3,
      last_saved_at: '2026-08-12T09:30:00+00:00',
    },
    audit_events: 36,
    sessions: [
      {
        id: 'a1b2c3d4e5f6',
        issued_at: '2026-08-13T08:00:00+00:00',
        expires_at: '2026-08-27T08:00:00+00:00',
      },
    ],
    upstreams: [
      { name: 'Anthropic', detail: 'No API key: extraction is unavailable', configured: false },
      { name: 'PubChem', detail: 'Compound lookup', configured: true },
    ],
    platform: {
      environment: 'development',
      release: 'local',
      llm_model: 'claude-sonnet-4-5',
      extraction_available: false,
      document_encryption: 'kms',
      access_token_ttl_minutes: 30,
      refresh_token_ttl_days: 14,
      audit_retention_days: 365,
      llm_daily_call_budget: 250,
    },
    ...overrides,
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  accountOverview.mockResolvedValue(overview());
  logoutAll.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

describe('Workspace', () => {
  // The page used to name four colleagues, a plan and three connected systems, none of which
  // existed. Everything it shows now has to come from the account it is signed in as.
  it('shows the signed-in account and its counted work rather than invented members', async () => {
    render(<WorkspacePage />);

    expect(await screen.findByText('chemist@askgrey.ai')).toBeInTheDocument();
    expect(screen.getByText('Screening — compound profiles')).toBeInTheDocument();
    expect(screen.getByText('36')).toBeInTheDocument();
    expect(screen.queryByText(/Dana Okoye/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Benchling/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Seats used/)).not.toBeInTheDocument();
    expect(accountOverview).toHaveBeenCalledWith('token-123');
  });

  it('says a data source is unavailable when the deployment has no key for it', async () => {
    render(<WorkspacePage />);

    expect(await screen.findByText('Not configured')).toBeInTheDocument();
    expect(screen.getByText('Available')).toBeInTheDocument();
  });

  it('prompts a first save instead of showing an empty table as a result', async () => {
    accountOverview.mockResolvedValue(
      overview({
        saved_work: { counts: {}, total: 0, last_saved_at: null },
        storage: {
          stored_papers: 0,
          stored_bytes: 0,
          retention_days: 90,
          next_expiry: null,
        },
      }),
    );
    render(<WorkspacePage />);

    expect(await screen.findByText('Nothing saved yet')).toBeInTheDocument();
    expect(screen.getByText('Nothing stored')).toBeInTheDocument();
  });

  it('explains itself when the overview cannot be loaded', async () => {
    accountOverview.mockRejectedValue(new Error('Session expired.'));
    render(<WorkspacePage />);

    expect(await screen.findByText('This workspace could not be loaded')).toBeInTheDocument();
    expect(screen.getByText('Session expired.')).toBeInTheDocument();
  });
});

describe('Settings', () => {
  it('reports the running configuration instead of sample values', async () => {
    render(
      <OnboardingProvider>
        <SettingsPage />
      </OnboardingProvider>,
    );

    expect(await screen.findByText('claude-sonnet-4-5')).toBeInTheDocument();
    expect(screen.getByText(/AWS KMS/)).toBeInTheDocument();
    expect(screen.getByText('365 days')).toBeInTheDocument();
    expect(screen.getByText('Not configured')).toBeInTheDocument();
    // The old page showed masked keys that were never read from anything.
    expect(screen.queryByText(/••••/)).not.toBeInTheDocument();
    expect(screen.queryByText(/US-East/)).not.toBeInTheDocument();
  });

  it('lists this account s live sign-ins', async () => {
    render(
      <OnboardingProvider>
        <SettingsPage />
      </OnboardingProvider>,
    );

    expect(await screen.findByText(/Signed in/)).toBeInTheDocument();
    expect(screen.getByText('a1b2c3d')).toBeInTheDocument();
  });

  // Revoking every session includes the one rendering the page, so the app must stop showing a
  // workspace it can no longer renew.
  it('signs the app out after revoking every session', async () => {
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    const user = userEvent.setup();
    render(
      <OnboardingProvider>
        <SettingsPage />
      </OnboardingProvider>,
    );

    await user.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));

    await waitFor(() => expect(logoutAll).toHaveBeenCalledWith('token-123'));
    expect(expired).toHaveBeenCalled();
    unsubscribe();
  });

  it('keeps the account signed in when the revocation fails', async () => {
    logoutAll.mockRejectedValue(new Error('Could not reach the server.'));
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    const user = userEvent.setup();
    render(
      <OnboardingProvider>
        <SettingsPage />
      </OnboardingProvider>,
    );

    await user.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));

    expect(await screen.findByText('Could not reach the server.')).toBeInTheDocument();
    expect(expired).not.toHaveBeenCalled();
    unsubscribe();
  });
});
