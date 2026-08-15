import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

function Exploding(): never {
  throw new Error('render blew up');
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ErrorBoundary', () => {
  it('renders children while nothing is wrong', () => {
    render(
      <ErrorBoundary>
        <p>workspace</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText('workspace')).toBeInTheDocument();
  });

  it('replaces a crashed tree with a recoverable message and logs the failure', () => {
    // React itself writes the caught error to console.error; silence it to keep output readable.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <ErrorBoundary>
        <Exploding />
      </ErrorBoundary>,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument();
    const logged = consoleError.mock.calls
      .map((call) => String(call[0]))
      .some((line) => line.includes('"event":"ui.crash"'));
    expect(logged).toBe(true);
  });
});
