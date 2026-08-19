import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider } from './auth';
import { useAuth } from './auth-context';
import { getAccessToken, notifySessionExpired } from './session';

const refresh = vi.fn();
const login = vi.fn();
const logout = vi.fn();
const me = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      refresh: () => refresh(),
      login: (...args: unknown[]) => login(...args),
      logout: () => logout(),
      me: (...args: unknown[]) => me(...args),
    },
  };
});

const USER = {
  id: 'u1',
  email: 'ada@lab.test',
  full_name: 'Ada Lab',
  role: 'owner',
  provider: 'password',
  created_at: '2026-01-01T00:00:00Z',
};

function Probe() {
  const { user, loading, login: signIn, logout: signOut } = useAuth();
  if (loading) return <p>loading</p>;
  return (
    <div>
      <p>{user ? user.email : 'signed out'}</p>
      <button onClick={() => void signIn('ada@lab.test', 'password123')}>sign in</button>
      <button onClick={() => signOut()}>sign out</button>
    </div>
  );
}

beforeEach(() => {
  me.mockResolvedValue(USER);
  logout.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe('AuthProvider', () => {
  it('restores the session from the refresh cookie rather than from storage', async () => {
    refresh.mockResolvedValue({ access_token: 'fresh', token_type: 'bearer' });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByText('ada@lab.test')).toBeInTheDocument());
    expect(refresh).toHaveBeenCalled();
    expect(me).toHaveBeenCalledWith('fresh');
  });

  it('shows a signed-out shell when no refresh cookie is present', async () => {
    refresh.mockRejectedValue(new Error('401'));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument());
    expect(getAccessToken()).toBeUndefined();
  });

  it('stops showing a signed-in shell once a request finds the session unrenewable', async () => {
    refresh.mockResolvedValue({ access_token: 'fresh', token_type: 'bearer' });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText('ada@lab.test')).toBeInTheDocument());

    act(() => notifySessionExpired());

    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument());
    expect(getAccessToken()).toBeUndefined();
  });

  it('never writes a token to localStorage and revokes the session on logout', async () => {
    refresh.mockRejectedValue(new Error('401'));
    login.mockResolvedValue({ access_token: 'in-memory-only', token_type: 'bearer' });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByText('sign in'));

    await waitFor(() => expect(screen.getByText('ada@lab.test')).toBeInTheDocument());
    expect(getAccessToken()).toBe('in-memory-only');
    expect(Object.keys(window.localStorage)).toHaveLength(0);

    await user.click(screen.getByText('sign out'));
    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument());
    expect(logout).toHaveBeenCalled();
    expect(getAccessToken()).toBeUndefined();
  });
});
