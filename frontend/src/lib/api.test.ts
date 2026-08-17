import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, formatErrorDetail } from './api';

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
    void api.refresh();
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
