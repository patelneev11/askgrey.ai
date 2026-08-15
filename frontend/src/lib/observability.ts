/**
 * Frontend logging and error reporting.
 *
 * One logger instead of scattered `console.*`: every line is a JSON object with an event name
 * and fields, so a user-reported problem can be reconstructed from the browser console (or
 * from Sentry breadcrumbs, which these become) rather than from prose.
 *
 * Nothing here may carry research content. Log the shape of what happened — how many papers,
 * which tab, which error code — never the query, the extraction goal, or a cell value.
 */
import * as Sentry from '@sentry/react';

type Level = 'debug' | 'info' | 'warn' | 'error';

export type LogFields = Record<string, string | number | boolean | null | undefined>;

const DSN = import.meta.env.VITE_SENTRY_DSN ?? '';
const ENVIRONMENT = import.meta.env.VITE_ENVIRONMENT ?? 'development';
const RELEASE = import.meta.env.VITE_RELEASE ?? 'dev';

let reportingEnabled = false;

/** Starts Sentry when a DSN is configured; a no-op otherwise, which is how dev and CI run. */
export function initObservability(): boolean {
  if (!DSN) return false;
  Sentry.init({
    dsn: DSN,
    environment: ENVIRONMENT,
    release: RELEASE,
    // Session replay and default PII would capture document text on screen; the product
    // promise is that research content stays in the workspace.
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeBreadcrumb: (breadcrumb) => {
      if (breadcrumb.category === 'console') return null;
      return breadcrumb;
    },
  });
  reportingEnabled = true;
  return true;
}

function emit(level: Level, event: string, fields: LogFields = {}): void {
  const line = JSON.stringify({ level, event, ts: new Date().toISOString(), ...fields });
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.info(line);

  if (reportingEnabled) {
    Sentry.addBreadcrumb({
      category: 'app',
      level: level === 'warn' ? 'warning' : level,
      message: event,
      data: fields,
    });
  }
}

export const logger = {
  debug: (event: string, fields?: LogFields) => emit('debug', event, fields),
  info: (event: string, fields?: LogFields) => emit('info', event, fields),
  warn: (event: string, fields?: LogFields) => emit('warn', event, fields),
  /** Records a failure and, when reporting is on, sends it as an event rather than a crumb. */
  error: (event: string, error?: unknown, fields?: LogFields) => {
    emit('error', event, { ...fields, reason: error instanceof Error ? error.message : String(error ?? '') });
    if (reportingEnabled) {
      Sentry.captureException(error instanceof Error ? error : new Error(event), {
        tags: { event },
      });
    }
  },
};

/** Ties errors to an account without shipping the address; the id is enough to correlate. */
export function identify(userId: string | null): void {
  if (!reportingEnabled) return;
  Sentry.setUser(userId ? { id: userId } : null);
}
