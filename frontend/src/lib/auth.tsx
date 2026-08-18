import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, type TokenResponse, type User } from './api';
import { AuthContext } from './auth-context';
import { identify, logger } from './observability';
import { onSessionExpired, setAccessToken } from './session';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    // Nothing survives a reload in memory, so the session is restored from the refresh
    // cookie the browser still holds. A 401 here simply means no session.
    const restore = async () => {
      try {
        const tokens = await api.refresh();
        setAccessToken(tokens.access_token);
        const current = await api.me(tokens.access_token);
        identify(current.id);
        if (!cancelled) setUser(current);
      } catch {
        setAccessToken(undefined);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // A request whose token could not be renewed means the session is really gone; drop the
  // signed-in user so the route guard asks for a sign-in instead of rendering a workspace
  // where every call fails.
  useEffect(
    () =>
      onSessionExpired(() => {
        logger.info('auth.session_expired');
        identify(null);
        setUser(null);
      }),
    [],
  );

  const completeSignIn = useCallback(async (tokens: TokenResponse) => {
    setAccessToken(tokens.access_token);
    const current = await api.me(tokens.access_token);
    identify(current.id);
    logger.info('auth.signed_in', { user_id: current.id, provider: current.provider });
    setUser(current);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      await completeSignIn(await api.login(email, password));
    },
    [completeSignIn],
  );

  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      await completeSignIn(await api.register(email, password, fullName));
    },
    [completeSignIn],
  );

  const logout = useCallback(() => {
    // Revoking server-side matters more than clearing memory: the cookie is what an
    // attacker with the device would otherwise keep replaying for two weeks.
    void api.logout().catch(() => undefined);
    logger.info('auth.signed_out');
    identify(null);
    setAccessToken(undefined);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
