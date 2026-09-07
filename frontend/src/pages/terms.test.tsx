import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider } from '@/lib/auth';

import { LoginPage } from './LoginPage';
import { TermsPage } from './TermsPage';

const terms = vi.fn();
const registerCall = vi.fn();
const ssoConfig = vi.fn();
const me = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      terms: (...args: unknown[]) => terms(...args),
      register: (...args: unknown[]) => registerCall(...args),
      ssoConfig: (...args: unknown[]) => ssoConfig(...args),
      me: (...args: unknown[]) => me(...args),
      refresh: () => Promise.reject(new Error('no session')),
    },
  };
});

const VERSION = '2026-09-07';

beforeEach(() => {
  terms.mockReset();
  registerCall.mockReset();
  ssoConfig.mockReset();
  me.mockReset();
  terms.mockResolvedValue({ version: VERSION });
  ssoConfig.mockResolvedValue({
    enabled: false,
    issuer: '',
    authorize_url: null,
  });
  registerCall.mockResolvedValue({
    access_token: 'token-123',
    token_type: 'bearer',
    user: {
      id: 'user-1',
      email: 'chemist@askgrey.ai',
      full_name: '',
      role: 'owner',
      provider: 'password',
      created_at: '2026-09-07T00:00:00+00:00',
      terms_version: VERSION,
      terms_accepted_at: '2026-09-07T00:00:01+00:00',
    },
  });
});

function renderLogin() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('the terms of agreement page', () => {
  it('shows the published version it is offering, without a session', async () => {
    render(
      <MemoryRouter>
        <TermsPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Terms of Agreement' })).toBeInTheDocument();
    expect(await screen.findByText(`Version ${VERSION}`)).toBeInTheDocument();
  });

  it('states the acceptable use the assistant enforces in code', async () => {
    render(
      <MemoryRouter>
        <TermsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/biological or chemical weapon/i)).toBeInTheDocument();
    expect(screen.getByText(/controlled substances or explosives/i)).toBeInTheDocument();
  });

  // A registration that could not read the terms must not be able to claim they were accepted,
  // so the page still renders its wording and the form (asserted below) refuses to submit.
  it('renders its wording even when the version cannot be read', async () => {
    terms.mockRejectedValue(new Error('offline'));
    render(
      <MemoryRouter>
        <TermsPage />
      </MemoryRouter>,
    );

    expect((await screen.findAllByText(/not a medical device/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^Version /)).not.toBeInTheDocument();
  });
});

describe('accepting the terms to register', () => {
  it('will not create an account until the researcher says they have read them', async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole('button', { name: /Create one/ }));
    const submit = screen.getByRole('button', { name: 'Create workspace' });
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole('checkbox'));
    expect(submit).toBeEnabled();
  });

  it('sends the version that was on screen, so the API can refuse a stale acceptance', async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole('button', { name: /Create one/ }));
    await waitFor(() => expect(terms).toHaveBeenCalled());
    await user.type(screen.getByLabelText('Work email'), 'chemist@askgrey.ai');
    await user.type(screen.getByLabelText(/^Password/), 'correct horse battery');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));

    await waitFor(() =>
      expect(registerCall).toHaveBeenCalledWith(
        'chemist@askgrey.ai',
        'correct horse battery',
        '',
        VERSION,
      ),
    );
  });

  it('asks again after leaving the register form and coming back', async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole('button', { name: /Create one/ }));
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: /Already have a workspace/ }));
    await user.click(screen.getByRole('button', { name: /Create one/ }));

    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Create workspace' })).toBeDisabled();
  });

  it('refuses to register at all when the terms could not be loaded', async () => {
    terms.mockRejectedValue(new Error('offline'));
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole('button', { name: /Create one/ }));
    await user.type(screen.getByLabelText('Work email'), 'chemist@askgrey.ai');
    await user.type(screen.getByLabelText(/^Password/), 'correct horse battery');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(registerCall).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be loaded/i);
  });
});

describe('revealing a typed password', () => {
  it('hides it by default and shows it only while the reveal is on', async () => {
    const user = userEvent.setup();
    renderLogin();

    const field = screen.getByLabelText(/^Password/);
    await user.type(field, 'correct horse battery');
    expect(field).toHaveAttribute('type', 'password');

    await user.click(screen.getByRole('button', { name: 'Show password' }));
    expect(field).toHaveAttribute('type', 'text');
    // The value is unchanged by revealing it: this is presentation only.
    expect(field).toHaveValue('correct horse battery');

    await user.click(screen.getByRole('button', { name: 'Hide password' }));
    expect(field).toHaveAttribute('type', 'password');
  });
});
