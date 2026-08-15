import { useEffect, useState, type FormEvent } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { Button } from '@/components/Button';
import { api, type SSOConfig } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

import styles from './LoginPage.module.css';

type Mode = 'login' | 'register';

export function LoginPage() {
  const { user, loading, login, register } = useAuth();
  const location = useLocation();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sso, setSso] = useState<SSOConfig | null>(null);

  useEffect(() => {
    api
      .ssoConfig()
      .then(setSso)
      .catch(() => setSso(null));
  }, []);

  if (!loading && user) {
    const from = (location.state as { from?: string } | null)?.from ?? '/literature';
    return <Navigate to={from} replace />;
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else {
        await register(email, password, fullName);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">
            ag
          </span>
          <span className={styles.brandName}>askgrey</span>
        </div>
        <h1 className={styles.heading}>
          {mode === 'login' ? 'Sign in to your workspace' : 'Create your workspace'}
        </h1>
        <p className={styles.tagline}>
          Grounded literature review — extract data from papers with every value traced back to the
          passage it came from.
        </p>

        <form className={styles.form} onSubmit={handleSubmit}>
          {mode === 'register' && (
            <label className={styles.field}>
              <span className={styles.label}>Full name</span>
              <input
                className={styles.input}
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                autoComplete="name"
              />
            </label>
          )}

          <label className={styles.field}>
            <span className={styles.label}>Work email</span>
            <input
              className={styles.input}
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
            />
          </label>

          <label className={styles.field}>
            <span className={styles.label}>Password</span>
            <input
              className={styles.input}
              type="password"
              required
              minLength={mode === 'register' ? 12 : undefined}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
            {mode === 'register' && (
              <span className={styles.hint}>Minimum 12 characters.</span>
            )}
          </label>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" fullWidth disabled={submitting}>
            {submitting ? 'Working…' : mode === 'login' ? 'Sign in' : 'Create workspace'}
          </Button>
        </form>

        {sso?.enabled && sso.authorize_url && (
          <>
            <div className={styles.divider}>
              <span>or</span>
            </div>
            <a className={styles.ssoLink} href={sso.authorize_url}>
              Continue with {new URL(sso.issuer).hostname}
            </a>
          </>
        )}

        <button
          type="button"
          className={styles.modeToggle}
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login');
            setError(null);
          }}
        >
          {mode === 'login'
            ? 'No workspace yet? Create one'
            : 'Already have a workspace? Sign in'}
        </button>
      </div>
    </div>
  );
}
