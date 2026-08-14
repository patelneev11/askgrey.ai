import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, type TokenPair, type User } from './api';
import { AuthContext } from './auth-context';
import { ACCESS_KEY, REFRESH_KEY } from './session';

function storeTokens(tokens: TokenPair): void {
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

function clearTokens(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const restore = async () => {
      const accessToken = window.localStorage.getItem(ACCESS_KEY);
      const refreshToken = window.localStorage.getItem(REFRESH_KEY);
      if (!accessToken) {
        if (!cancelled) setLoading(false);
        return;
      }

      try {
        const current = await api.me(accessToken);
        if (!cancelled) setUser(current);
      } catch {
        // The access token expired; fall back to the refresh token before signing out.
        if (refreshToken) {
          try {
            const tokens = await api.refresh(refreshToken);
            storeTokens(tokens);
            const current = await api.me(tokens.access_token);
            if (!cancelled) setUser(current);
          } catch {
            clearTokens();
          }
        } else {
          clearTokens();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const completeSignIn = useCallback(async (tokens: TokenPair) => {
    storeTokens(tokens);
    setUser(await api.me(tokens.access_token));
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
    clearTokens();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
