import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';

import { BrandMark } from '@/components/BrandMark';
import { Button } from '@/components/Button';
import { PasswordInput } from '@/components/PasswordInput';
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
  // The version of the terms this form is offering. Registration submits it, and the API refuses
  // any version other than the published one, so an acceptance can only name wording that was on
  // screen. Null means the terms could not be read, and registration stays unavailable.
  const [termsVersion, setTermsVersion] = useState<string | null>(null);
  const [acceptedTerms, setAcceptedTerms] = useState(false);

  useEffect(() => {
    api
      .ssoConfig()
      .then(setSso)
      .catch(() => setSso(null));
    api
      .terms()
      .then((info) => setTermsVersion(info.version))
      .catch(() => setTermsVersion(null));
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
      } else if (termsVersion === null) {
        setError('The terms of agreement could not be loaded. Reload the page and try again.');
      } else {
        await register(email, password, fullName, termsVersion);
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
          <BrandMark
            className={styles.brandMark}
            size={40}
            aria-hidden="true"
            role="presentation"
          />
          <span className={styles.brandText}>
            <span className={styles.brandName}>askgrey</span>
            <span className={styles.brandSubtitle}>Research Intelligence</span>
          </span>
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
            <PasswordInput
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

          {mode === 'register' && (
            <label className={styles.consent}>
              <input
                type="checkbox"
                className={styles.checkbox}
                checked={acceptedTerms}
                onChange={(event) => setAcceptedTerms(event.target.checked)}
              />
              <span>
                I have read, understood and comply with the{' '}
                <Link className={styles.termsLink} to="/terms" target="_blank" rel="noreferrer">
                  Terms of Agreement
                </Link>
                .
              </span>
            </label>
          )}

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            fullWidth
            disabled={submitting || (mode === 'register' && !acceptedTerms)}
          >
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
            // Leaving the register form and coming back must ask again rather than remember a
            // tick from a session the researcher may have abandoned.
            setAcceptedTerms(false);
          }}
        >
          {mode === 'login'
            ? 'No workspace yet? Create one'
            : 'Already have a workspace? Sign in'}
        </button>

        <Link className={styles.footerLink} to="/terms">
          Terms of Agreement
        </Link>
      </div>
    </div>
  );
}
