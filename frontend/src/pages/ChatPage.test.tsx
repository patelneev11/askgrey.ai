import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import type { AssistantLimits, ChatToolStep } from '@/lib/chat';
import { setAccessToken } from '@/lib/session';

import { ChatPage } from './ChatPage';

const listConversations = vi.fn();
const loadConversation = vi.fn();
const startConversation = vi.fn();
const deleteConversation = vi.fn();
const chatTools = vi.fn();
const chatLimits = vi.fn();
const listArtifacts = vi.fn();
const listProtocols = vi.fn();
const sendChatMessage = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      listConversations: (...args: unknown[]) => listConversations(...args),
      loadConversation: (...args: unknown[]) => loadConversation(...args),
      startConversation: (...args: unknown[]) => startConversation(...args),
      deleteConversation: (...args: unknown[]) => deleteConversation(...args),
      chatTools: (...args: unknown[]) => chatTools(...args),
      chatLimits: (...args: unknown[]) => chatLimits(...args),
      listArtifacts: (...args: unknown[]) => listArtifacts(...args),
      listProtocols: (...args: unknown[]) => listProtocols(...args),
      sendChatMessage: (...args: unknown[]) => sendChatMessage(...args),
    },
  };
});

/** A scripted server-sent event stream, split across reads the way a real turn arrives. */
function stream(...frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    },
  });
}

function event(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

function step(overrides: Partial<ChatToolStep> = {}): ChatToolStep {
  return {
    id: 'tool-1',
    tool: 'search_pubmed',
    title: 'Search PubMed',
    arguments: { query: 'ziprasidone QT' },
    ok: true,
    summary: '3 papers found.',
    citations: [
      {
        label: 'QTc prolongation with ziprasidone',
        source: 'PubMed',
        identifier: '12345678',
        url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
      },
    ],
    detail: null,
    ...overrides,
  };
}

function limits(overrides: Partial<AssistantLimits> = {}): AssistantLimits {
  return {
    scope_version: '2026-08-13',
    scope_purpose: 'Biomedical R&D research support: literature, trials, protocols and grants.',
    scope_refusal: 'I only answer questions about biomedical R&D work in this workspace.',
    daily_spent_usd: 0.42,
    daily_cap_usd: 2,
    monthly_spent_usd: 3.5,
    monthly_cap_usd: 25,
    exhausted_cap: '',
    max_tool_steps: 6,
    max_message_chars: 4000,
    ...overrides,
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  listConversations.mockResolvedValue([]);
  chatTools.mockResolvedValue([
    {
      name: 'search_pubmed',
      title: 'Search PubMed',
      description: 'Search the literature.',
      tab: 'literature',
    },
  ]);
  listArtifacts.mockResolvedValue([]);
  listProtocols.mockResolvedValue([]);
  chatLimits.mockResolvedValue(limits());
  startConversation.mockResolvedValue({
    id: 'conv-1',
    title: '',
    message_count: 0,
    created_at: '2026-08-13T14:00:00Z',
    updated_at: '2026-08-13T14:00:00Z',
  });
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

describe('Assistant tab', () => {
  it('explains what it can do before anything is asked', async () => {
    render(<ChatPage />);

    expect(await screen.findByText(/Ask about the work you already have/)).toBeInTheDocument();
    // The capability list is the server's, so the tab cannot imply a tool that does not exist.
    await waitFor(() => expect(screen.getByText(/Search PubMed/)).toBeInTheDocument());
    expect(screen.getByText(/require expert review/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot file anything in an external lab notebook/i)).toBeInTheDocument();
  });

  it('streams the answer and shows the tools behind it with their sources', async () => {
    sendChatMessage.mockResolvedValue(
      stream(
        event({ type: 'tool_start', id: 'tool-1', tool: 'search_pubmed', title: 'Search PubMed', arguments: { query: 'ziprasidone QT' } }),
        event({ type: 'tool_result', step: step() }),
        event({ type: 'text', text: 'Three trials report ' }),
        event({ type: 'text', text: 'QTc prolongation.' }),
        event({ type: 'done', conversation_id: 'conv-1', message_id: 'msg-1' }),
      ),
    );
    render(<ChatPage />);

    await userEvent.type(
      await screen.findByLabelText('Message the assistant'),
      'What is known about ziprasidone and QTc?',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByText('Three trials report QTc prolongation.')).toBeInTheDocument();
    expect(screen.getByText('3 papers found.')).toBeInTheDocument();
    const citation = screen.getByRole('link', {
      name: /QTc prolongation with ziprasidone · 12345678/,
    });
    expect(citation).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/12345678/');
    expect(startConversation).toHaveBeenCalledWith('token-123');
    expect(sendChatMessage).toHaveBeenCalledWith(
      'conv-1',
      'What is known about ziprasidone and QTc?',
      [],
      'token-123',
    );
  });

  it('marks a failed tool rather than folding it into the prose', async () => {
    sendChatMessage.mockResolvedValue(
      stream(
        event({
          type: 'tool_result',
          step: step({ ok: false, summary: 'PubChem could not be reached.', citations: [] }),
        }),
        event({ type: 'text', text: 'I could not check that.' }),
        event({ type: 'done', conversation_id: 'conv-1', message_id: 'msg-1' }),
      ),
    );
    render(<ChatPage />);

    await userEvent.type(await screen.findByLabelText('Message the assistant'), 'Profile aspirin');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByText('PubChem could not be reached.')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('sends the saved work the researcher referenced, by id', async () => {
    listArtifacts.mockResolvedValue([
      {
        id: 'art-9',
        kind: 'screening_admet',
        title: 'Ziprasidone ADMET',
        subtitle: 'hERG, CYP',
        created_at: '2026-08-01T10:00:00Z',
        updated_at: '2026-08-01T10:00:00Z',
      },
    ]);
    sendChatMessage.mockResolvedValue(
      stream(event({ type: 'done', conversation_id: 'conv-1', message_id: 'msg-1' })),
    );
    render(<ChatPage />);

    await userEvent.click(await screen.findByRole('button', { name: 'Reference' }));
    await userEvent.click(await screen.findByRole('button', { name: /Ziprasidone ADMET/ }));
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'How reliable is that?');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    await waitFor(() =>
      expect(sendChatMessage).toHaveBeenCalledWith(
        'conv-1',
        'How reliable is that?',
        [{ kind: 'saved_work', id: 'art-9' }],
        'token-123',
      ),
    );
  });

  it('says the model call budget is spent instead of failing silently', async () => {
    sendChatMessage.mockRejectedValue(new ApiError('too many requests', 429));
    render(<ChatPage />);

    await userEvent.type(await screen.findByLabelText('Message the assistant'), 'Anything');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/model call budget/i);
  });

  it('says the assistant is unconfigured when the server has no key', async () => {
    sendChatMessage.mockRejectedValue(new ApiError('needs a key', 503));
    render(<ChatPage />);

    await userEvent.type(await screen.findByLabelText('Message the assistant'), 'Anything');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Anthropic API key/);
  });

  it('reopens a stored conversation with its trace intact', async () => {
    listConversations.mockResolvedValue([
      {
        id: 'conv-7',
        title: 'Ziprasidone liabilities',
        message_count: 2,
        created_at: '2026-08-10T10:00:00Z',
        updated_at: '2026-08-10T10:05:00Z',
      },
    ]);
    loadConversation.mockResolvedValue({
      id: 'conv-7',
      title: 'Ziprasidone liabilities',
      message_count: 2,
      created_at: '2026-08-10T10:00:00Z',
      updated_at: '2026-08-10T10:05:00Z',
      messages: [
        {
          id: 'm1',
          role: 'user',
          text: 'Any QT risk?',
          steps: [],
          created_at: '2026-08-10T10:00:00Z',
        },
        {
          id: 'm2',
          role: 'assistant',
          text: 'Three trials report it.',
          steps: [step()],
          created_at: '2026-08-10T10:01:00Z',
        },
      ],
    });
    render(<ChatPage />);

    await userEvent.click(
      await screen.findByRole('button', { name: 'Ziprasidone liabilities 2 messages' }),
    );

    expect(await screen.findByText('Three trials report it.')).toBeInTheDocument();
    expect(screen.getByText('3 papers found.')).toBeInTheDocument();
    expect(loadConversation).toHaveBeenCalledWith('conv-7', 'token-123');
  });

  it('shows the notice when a turn was cut short', async () => {
    sendChatMessage.mockResolvedValue(
      stream(
        event({ type: 'text', text: 'Partial…' }),
        event({ type: 'notice', message: 'The answer was cut short by the length limit.' }),
      ),
    );
    render(<ChatPage />);

    await userEvent.type(await screen.findByLabelText('Message the assistant'), 'Long question');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByText(/cut short by the length limit/)).toBeInTheDocument();
  });

  it('states the scope and what is left to spend, from the server', async () => {
    render(<ChatPage />);

    expect(await screen.findByText(/Biomedical R&D research support/)).toBeInTheDocument();
    expect(screen.getByText('$0.42 of $2.00')).toBeInTheDocument();
    expect(screen.getByText('$3.50 of $25.00')).toBeInTheDocument();
    expect(screen.getByText('up to 6')).toBeInTheDocument();
    expect(screen.getByText(/Scope policy 2026-08-13/)).toBeInTheDocument();
  });

  it('says so rather than hiding it when a cap is not enforced', async () => {
    chatLimits.mockResolvedValue(limits({ daily_cap_usd: 0, monthly_cap_usd: 0 }));
    render(<ChatPage />);

    expect(await screen.findByText('$0.42 (no cap)')).toBeInTheDocument();
  });

  it('closes the composer when the account has spent its budget', async () => {
    chatLimits.mockResolvedValue(
      limits({ exhausted_cap: 'daily', daily_spent_usd: 2, daily_cap_usd: 2 }),
    );
    render(<ChatPage />);

    expect(await screen.findByText(/used its daily assistant budget/)).toBeInTheDocument();
    expect(screen.getByText(/resets at 00:00 UTC/)).toBeInTheDocument();
    expect(screen.getByLabelText('Message the assistant')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
    expect(sendChatMessage).not.toHaveBeenCalled();
  });

  it('refuses to send a message longer than the server accepts', async () => {
    chatLimits.mockResolvedValue(limits({ max_message_chars: 20 }));
    render(<ChatPage />);

    await userEvent.type(
      await screen.findByLabelText('Message the assistant'),
      'a question far longer than twenty characters',
    );

    expect(screen.getByText(/the server accepts 20/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
    expect(sendChatMessage).not.toHaveBeenCalled();
  });

  it('refuses an over-length message sent with Enter, not only with the button', async () => {
    // A disabled button is not the guard: Enter sends too, and the rejected request would put
    // the server's own validation string in front of the researcher.
    chatLimits.mockResolvedValue(limits({ max_message_chars: 20 }));
    render(<ChatPage />);

    const box = await screen.findByLabelText('Message the assistant');
    await userEvent.type(box, 'a question far longer than twenty characters');
    await userEvent.type(box, '{Enter}');

    expect(sendChatMessage).not.toHaveBeenCalled();
    expect(startConversation).not.toHaveBeenCalled();
    expect(screen.getByText(/the server accepts 20/)).toBeInTheDocument();
  });

  it('re-reads the budget after a turn, so the figure is what the answer cost', async () => {
    sendChatMessage.mockResolvedValue(
      stream(
        event({ type: 'text', text: 'Three trials.' }),
        event({ type: 'done', conversation_id: 'conv-1', message_id: 'msg-1' }),
      ),
    );
    chatLimits.mockResolvedValueOnce(limits()).mockResolvedValue(limits({ daily_spent_usd: 0.61 }));
    render(<ChatPage />);

    await userEvent.type(await screen.findByLabelText('Message the assistant'), 'Any QT risk?');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByText('$0.61 of $2.00')).toBeInTheDocument();
  });
});
