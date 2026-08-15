import { afterEach, describe, expect, it, vi } from 'vitest';

import { logger } from './observability';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('logger', () => {
  it('writes one JSON object per line with the event and its fields', () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);

    logger.info('api.ok', { route: '/pubmed/search', duration_ms: 12 });

    expect(info).toHaveBeenCalledTimes(1);
    const line = JSON.parse(info.mock.calls[0][0] as string) as Record<string, unknown>;
    expect(line).toMatchObject({
      level: 'info',
      event: 'api.ok',
      route: '/pubmed/search',
      duration_ms: 12,
    });
    expect(typeof line.ts).toBe('string');
  });

  it('records the reason on the error line rather than the raw exception', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    logger.error('api.unreachable', new Error('Failed to fetch'), { route: '/grants/search' });

    const line = JSON.parse(error.mock.calls[0][0] as string) as Record<string, unknown>;
    expect(line).toMatchObject({
      level: 'error',
      event: 'api.unreachable',
      route: '/grants/search',
      reason: 'Failed to fetch',
    });
  });

  it('stays a console-only no-op when no DSN is configured', () => {
    // Reporting is off in dev and CI, so nothing may throw for want of a Sentry client.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(() => logger.warn('api.timeout', { route: '/pdf/extract' })).not.toThrow();
    expect(warn).toHaveBeenCalledTimes(1);
  });
});
