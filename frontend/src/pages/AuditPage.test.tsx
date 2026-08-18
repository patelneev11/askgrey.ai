import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuditEvent, AuditFeed } from '@/lib/api';
import { setAccessToken } from '@/lib/session';

import { AuditPage } from './AuditPage';

const auditEvents = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: { auditEvents: (...args: unknown[]) => auditEvents(...args) },
  };
});

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: 'e1f2a3b4c5d6',
    occurred_at: '2026-08-13T14:22:08+00:00',
    event: 'auth.login',
    kind: 'human',
    outcome: 'success',
    client_ip: '203.0.113.7',
    detail: {},
    ...overrides,
  };
}

function feed(events: AuditEvent[], retentionDays = 365): AuditFeed {
  return { events, retention_days: retentionDays };
}

beforeEach(() => {
  setAccessToken('token-123');
  auditEvents.mockResolvedValue(feed([event()]));
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

describe('Audit Trails', () => {
  it('renders the account events the API returned, not sample data', async () => {
    render(<AuditPage />);

    expect(await screen.findByText('Signed in')).toBeInTheDocument();
    expect(screen.queryByText('Sample data')).not.toBeInTheDocument();
    expect(screen.queryByText(/Exported protocol to Benchling/)).not.toBeInTheDocument();
    expect(auditEvents).toHaveBeenCalledWith(undefined, 'token-123');
  });

  // The filter has to reach the server, because the page only ever holds one page of events.
  it('asks the server for one kind when a filter is chosen', async () => {
    auditEvents.mockResolvedValue(
      feed([event({ id: 'x9y8z7w6', event: 'export.downloaded', kind: 'export' })]),
    );
    render(<AuditPage />);
    await screen.findByText('Downloaded a review table');

    await userEvent.click(screen.getByRole('button', { name: 'Exports' }));

    await waitFor(() => expect(auditEvents).toHaveBeenCalledWith('export', 'token-123'));
    expect(screen.getByRole('button', { name: 'Exports' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('states the retention the API reports and makes no 21 CFR Part 11 claim', async () => {
    auditEvents.mockResolvedValue(feed([event()], 90));
    render(<AuditPage />);

    expect(await screen.findByText(/kept for 90 days/)).toBeInTheDocument();
    expect(screen.queryByText(/7 years/)).not.toBeInTheDocument();
    expect(screen.getByText(/not a 21 CFR Part 11 archive/)).toBeInTheDocument();
  });

  it('shows the model vendor an agent event was sent to, and no document text', async () => {
    auditEvents.mockResolvedValue(
      feed([
        event({
          event: 'document.sent_to_llm',
          kind: 'agent',
          detail: { source: 'paper.pdf', bytes: 4096, vendor: 'anthropic' },
        }),
      ]),
    );
    render(<AuditPage />);

    const entry = await screen.findByRole('listitem');
    expect(entry).toHaveTextContent('Sent a document to the model vendor');
    expect(entry).toHaveTextContent('vendor anthropic');
    expect(entry).not.toHaveTextContent('%PDF');
  });

  it('explains an empty trail rather than showing a blank pane', async () => {
    auditEvents.mockResolvedValue(feed([]));
    render(<AuditPage />);

    expect(await screen.findByText('No recorded activity yet')).toBeInTheDocument();
  });

  it('reports a failed load instead of implying nothing has happened', async () => {
    auditEvents.mockRejectedValue(new Error('Session expired'));
    render(<AuditPage />);

    expect(await screen.findByText('The audit trail could not be loaded')).toBeInTheDocument();
    expect(screen.getByText('Session expired')).toBeInTheDocument();
    expect(screen.queryByText('No recorded activity yet')).not.toBeInTheDocument();
  });

  it('shows a loading state while the first page is in flight', () => {
    auditEvents.mockReturnValue(new Promise(() => {}));
    render(<AuditPage />);

    expect(screen.getByText('Loading')).toBeInTheDocument();
  });

  it('marks a failed event so a denied action is not read as a successful one', async () => {
    auditEvents.mockResolvedValue(
      feed([event({ event: 'literature.document_deleted', outcome: 'failure' })]),
    );
    render(<AuditPage />);

    const entry = await screen.findByRole('listitem');
    expect(entry).toHaveTextContent('failure');
  });
});
