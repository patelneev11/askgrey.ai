import { useState, type InputHTMLAttributes } from 'react';

import styles from './PasswordInput.module.css';

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>;

function EyeIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" aria-hidden="true">
      <path d="M1.5 10S4.6 4.5 10 4.5 18.5 10 18.5 10 15.4 15.5 10 15.5 1.5 10 1.5 10Z" strokeWidth="1.3" />
      <circle cx="10" cy="10" r="2.6" strokeWidth="1.3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" aria-hidden="true">
      <path d="M1.5 10S4.6 4.5 10 4.5 18.5 10 18.5 10 15.4 15.5 10 15.5 1.5 10 1.5 10Z" strokeWidth="1.3" />
      <circle cx="10" cy="10" r="2.6" strokeWidth="1.3" />
      <path d="M3 17 17 3" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/**
 * A password field with a reveal toggle.
 *
 * The visibility lives here rather than in the form: it is presentation, it must reset to hidden
 * whenever the field is remounted, and nothing outside needs to know whether the characters are
 * on screen. The value stays in the caller's state and is never written anywhere else — no
 * logging, no DOM attribute — so revealing it costs nothing beyond the shoulder next to you.
 */
export function PasswordInput({ className, ...rest }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <span className={styles.wrap}>
      <input
        {...rest}
        type={visible ? 'text' : 'password'}
        className={[styles.input, className].filter(Boolean).join(' ')}
      />
      <button
        type="button"
        className={styles.toggle}
        onClick={() => setVisible(!visible)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        // A reveal button is not a stop on the way to the submit button.
        tabIndex={-1}
      >
        {visible ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </span>
  );
}
