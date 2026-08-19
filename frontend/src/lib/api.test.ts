import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, formatErrorDetail } from './api';
import { getAccessToken, onSessionExpired, setAccessToken } from './session';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('request timeouts', () => {
  it('aborts and reports a timeout instead of hanging when the backend never answers', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );

    const pending = api.login('user@example.org', 'password-1234');
    const assertion = expect(pending).rejects.toThrow(/did not respond within/);
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });
});

describe('refresh', () => {
  it('shares one request between overlapping callers, so the rotated token is never replayed', async () => {
    let settle: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          settle = resolve;
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const first = api.refresh();
    const second = api.refresh();
    settle(new Response(JSON.stringify({ access_token: 'a', token_type: 'bearer' })));

    expect(await first).toEqual(await second);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // The next refresh is a genuinely new one, not the cached result of the last.
    settle = () => undefined;
    const third = api.refresh();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // Settled before leaving: an in-flight refresh is shared module state, and every later
    // caller would await this same never-resolving promise.
    settle(new Response(JSON.stringify({ access_token: 'b', token_type: 'bearer' })));
    await third;
  });
});

describe('an expired access token', () => {
  const pdf = () => new File(['%PDF-1.4'], 'trial.pdf', { type: 'application/pdf' });

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  afterEach(() => setAccessToken(undefined));

  it('is renewed and the request retried, rather than surfacing "Not authenticated"', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: 'Not authenticated' }, 401))
      .mockResolvedValueOnce(json({ access_token: 'fresh', token_type: 'bearer' }))
      .mockResolvedValueOnce(json({ table_id: 't1', columns: [], rows: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.extractFromUpload(pdf(), 'sample size', 'stale')).resolves.toMatchObject({
      table_id: 't1',
    });

    const routes = fetchMock.mock.calls.map((call) => call[0] as string);
    expect(routes).toEqual([
      '/api/pdf-extraction/upload',
      '/api/auth/refresh',
      '/api/pdf-extraction/upload',
    ]);
    // The retry carries the renewed token, and it is now the session's token.
    const retryHeaders = fetchMock.mock.calls[2][1].headers as Headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer fresh');
    expect(getAccessToken()).toBe('fresh');
  });

  it('ends the session when the refresh cookie cannot renew it either', async () => {
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    setAccessToken('stale');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: 'Not authenticated' }, 401))
      .mockResolvedValueOnce(json({ detail: 'Not authenticated' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.extractFromUpload(pdf(), 'sample size', 'stale')).rejects.toThrow(
      /session expired/i,
    );

    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeUndefined();
    unsubscribe();
  });

  it('does not retry a rejected sign-in: a 401 there is the wrong password', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ detail: 'Invalid credentials' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.login('user@example.org', 'wrong-password')).rejects.toThrow(
      /Invalid credentials/,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retries once only, so a server that always 401s cannot loop', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: 'Not authenticated' }, 401))
      .mockResolvedValueOnce(json({ access_token: 'fresh', token_type: 'bearer' }))
      .mockResolvedValueOnce(json({ detail: 'Not authenticated' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.loadWorkspace('stale')).rejects.toThrow(/Not authenticated/);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe('formatErrorDetail', () => {
  it('passes through the string detail of a raised HTTPException', () => {
    expect(formatErrorDetail('Email is already registered')).toBe('Email is already registered');
  });

  it('joins the messages of a pydantic 422 issue list', () => {
    expect(
      formatErrorDetail([
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'password'], msg: 'String should have at least 12 characters' },
      ]),
    ).toBe('value is not a valid email address. String should have at least 12 characters');
  });

  it('returns undefined for shapes it cannot render, so the caller falls back', () => {
    expect(formatErrorDetail(undefined)).toBeUndefined();
    expect(formatErrorDetail({ unexpected: true })).toBeUndefined();
    expect(formatErrorDetail([{ type: 'value_error' }])).toBeUndefined();
  });
});
