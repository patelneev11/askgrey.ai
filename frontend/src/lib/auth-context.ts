import { createContext, useContext } from 'react';

import type { User } from './api';

export interface AuthContextValue {
  user: User | null;
  /** True until the stored session has been validated against the API on first load. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /**
   * `termsVersion` is the version the register form displayed; the API refuses any other, so an
   * acceptance always names the wording that was on screen.
   */
  register: (
    email: string,
    password: string,
    fullName: string,
    termsVersion: string,
  ) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return context;
}
