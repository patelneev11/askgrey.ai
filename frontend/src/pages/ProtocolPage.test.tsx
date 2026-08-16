import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  ChecklistItem,
  ElnExportPayload,
  ProtocolDraft,
  ProtocolReview,
  RecalculationResponse,
} from '@/lib/protocols';

import { ProtocolPage } from './ProtocolPage';

const draftProtocol = vi.fn();
const reagentChecklist = vi.fn();
const reviewControls = vi.fn();
const recalculate = vi.fn();
const saveProtocol = vi.fn();
const updateProtocol = vi.fn();
const protocolHistory = vi.fn();
const exportEln = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      draftProtocol: (...args: unknown[]) => draftProtocol(...args),
      reagentChecklist: (...args: unknown[]) => reagentChecklist(...args),
      reviewControls: (...args: unknown[]) => reviewControls(...args),
      recalculate: (...args: unknown[]) => recalculate(...args),
      saveProtocol: (...args: unknown[]) => saveProtocol(...args),
      updateProtocol: (...args: unknown[]) => updateProtocol(...args),
      protocolHistory: (...args: unknown[]) => protocolHistory(...args),
      exportEln: (...args: unknown[]) => exportEln(...args),
    },
  };
});

const GOAL = 'Design a Western blot protocol to measure p53 expression in MCF-7 cells';

function draft(overrides: Partial<ProtocolDraft> = {}): ProtocolDraft {
  return {
    title: 'Western blot for p53',
    goal: GOAL,
    assay_type: 'western blot',
    summary: 'Lyse, resolve, immunoblot.',
    materials: [
      {
        name: 'RIPA lysis buffer',
        amount: '200 uL per well',
        vendor_or_catalog: '',
        storage: '4 C',
        note: '',
      },
    ],
    steps: [
      {
        id: 'step-1',
        order: 1,
        title: 'Harvest treated cells',
        instruction: 'Wash twice with ice-cold PBS and scrape into RIPA buffer.',
        duration: '15 min',
        temperature: '4 C',
        equipment: [],
        critical_note: 'keep lysates on ice',
      },
      {
        id: 'step-2',
        order: 2,
        title: 'Clear lysates',
        instruction: 'Centrifuge at 14000 x g and keep the supernatant.',
        duration: '10 min',
        temperature: '4 C',
        equipment: [],
        critical_note: '',
      },
    ],
    total_duration: '2 days',
    expected_outcomes: ['A 53 kDa band'],
    origin: 'agent_drafted',
    disclaimer: 'Agent-drafted content. Requires qualified researcher review before lab use.',
    model: 'claude-test',
    drafted_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const CHECKLIST: ChecklistItem[] = [
  {
    id: 'storage-1',
    category: 'storage',
    subject: 'RIPA lysis buffer',
    detail: '4 C',
    quote: 'storage 4 C',
    step_id: '',
    step_order: null,
  },
  {
    id: 'spin-1',
    category: 'spin_speed',
    subject: 'Step 2: Clear lysates',
    detail: '14000 x g',
    quote: 'Centrifuge at 14000 x g',
    step_id: 'step-2',
    step_order: 2,
  },
];

const REVIEW: ProtocolReview = {
  assay_type: 'western blot',
  summary: 'No loading control is written down.',
  controls: [
    {
      name: 'Loading control (GAPDH)',
      kind: 'loading',
      status: 'missing',
      rationale: 'Band intensities cannot be compared without one.',
      suggested_after_step: 2,
    },
  ],
  reagent_checklist: CHECKLIST,
  missing_control_count: 1,
  origin: 'agent_drafted',
  disclaimer: 'Agent-drafted content. Requires qualified researcher review before lab use.',
  scope_note:
    'Control analysis only. This is an agent-drafted review of controls and reagent handling, not validation of the protocol or its science.',
  model: 'claude-test',
  reviewed_at: '2026-01-01T00:00:00Z',
};

function mixResponse(total: string): RecalculationResponse {
  return {
    outcomes: [
      {
        id: 'master-mix',
        step_id: '',
        kind: 'master_mix',
        result: {
          kind: 'master_mix',
          reactions: 24,
          replicates: 1,
          overage_percent: '10',
          effective_reactions: '26.4',
          lines: [
            {
              name: 'Primary antibody',
              per_reaction_volume: { value: '5', unit: 'uL' },
              total_volume: { value: total, unit: 'uL' },
              basis: '5 uL x 26.4',
              note: '',
            },
          ],
          per_reaction_volume: { value: '5', unit: 'uL' },
          total_volume: { value: total, unit: 'uL' },
          label: '',
          notes: [],
        },
        error: null,
      },
    ],
  };
}

const EXPORT: ElnExportPayload = {
  provider: 'benchling',
  integration_status: 'schema_ready_untested',
  integration_note: 'Built from Benchling public API documentation and never exercised against a live account.',
  endpoint: 'POST /api/v2/entries',
  entry: {
    name: 'Western blot for p53',
    folderId: 'lib_A1',
    entryTemplateId: null,
    schemaId: null,
    customFields: { 'AskGrey review status': { value: 'Agent-drafted content.' } },
  },
  notes: [{ type: 'text', text: 'Agent-drafted content. Requires qualified researcher review.' }],
  warnings: ['untested'],
};

beforeEach(() => {
  vi.clearAllMocks();
  draftProtocol.mockResolvedValue(draft());
  reagentChecklist.mockResolvedValue(CHECKLIST);
  reviewControls.mockResolvedValue(REVIEW);
  recalculate.mockResolvedValue(mixResponse('132'));
  saveProtocol.mockImplementation((protocol: ProtocolDraft) =>
    Promise.resolve({
      id: 'protocol-1',
      version: 1,
      protocol,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }),
  );
  updateProtocol.mockImplementation((_id: string, protocol: ProtocolDraft) =>
    Promise.resolve({
      id: 'protocol-1',
      version: 2,
      protocol: { ...protocol, origin: 'researcher_edited' as const },
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:01:00Z',
    }),
  );
  protocolHistory.mockResolvedValue({
    id: 'protocol-1',
    current_version: 1,
    versions: [
      {
        version: 1,
        change_summary: 'Initial draft saved',
        changes: [],
        author_user_id: 'user-1',
        created_at: '2026-01-01T00:00:00Z',
      },
    ],
  });
  exportEln.mockResolvedValue(EXPORT);
});

async function generate(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Experimental goal'), GOAL);
  await user.click(screen.getByRole('button', { name: 'Draft protocol' }));
  await screen.findByDisplayValue('Harvest treated cells');
}

describe('ProtocolPage — drafting', () => {
  it('renders the review disclaimer before any protocol exists and keeps it after drafting', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);

    expect(screen.getByRole('note')).toHaveTextContent(
      /Agent-drafted content\. Requires qualified researcher review before lab use\./i,
    );

    await generate(user);

    expect(screen.getByRole('note')).toHaveTextContent(
      /Agent-drafted content\. Requires qualified researcher review before lab use\./i,
    );
  });

  it('sends the goal to the backend and renders the returned steps', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);

    await generate(user);

    expect(draftProtocol).toHaveBeenCalledWith(
      expect.objectContaining({ goal: GOAL }),
      undefined,
    );
    expect(screen.getByDisplayValue('Clear lysates')).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'RIPA lysis buffer' })).toBeInTheDocument();
  });

  it('refuses to call the model for a goal too short to draft from', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);

    await user.type(screen.getByLabelText('Experimental goal'), 'blot');
    await user.click(screen.getByRole('button', { name: 'Draft protocol' }));

    expect(draftProtocol).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/Describe the experiment/i);
  });
});

describe('ProtocolPage — editing', () => {
  it('edits a step and saves it as a new version whose changelog is shown', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);
    await generate(user);

    await user.click(screen.getByRole('button', { name: 'Save version' }));
    await waitFor(() => expect(saveProtocol).toHaveBeenCalled());

    const instruction = screen.getByLabelText('Step 1 instruction');
    await user.clear(instruction);
    await user.type(instruction, 'Wash three times with ice-cold PBS.');

    protocolHistory.mockResolvedValue({
      id: 'protocol-1',
      current_version: 2,
      versions: [
        {
          version: 2,
          change_summary: '1 change(s)',
          changes: [
            {
              kind: 'modified',
              field: 'steps.step-1.instruction',
              label: 'Step 1 instruction edited',
              before: 'Wash twice',
              after: 'Wash three times',
            },
          ],
          author_user_id: 'user-1',
          created_at: '2026-01-01T00:01:00Z',
        },
      ],
    });
    await user.click(screen.getByRole('button', { name: 'Save version' }));

    await waitFor(() =>
      expect(updateProtocol).toHaveBeenCalledWith(
        'protocol-1',
        expect.objectContaining({
          steps: expect.arrayContaining([
            expect.objectContaining({
              id: 'step-1',
              instruction: 'Wash three times with ice-cold PBS.',
            }),
          ]),
        }),
        '',
        undefined,
      ),
    );
    expect(await screen.findByText('Step 1 instruction edited')).toBeInTheDocument();
    expect(screen.getByText(/researcher-edited/)).toBeInTheDocument();
  });

  it('reorders steps and renumbers them without rewriting their text', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);
    await generate(user);

    await user.click(screen.getByRole('button', { name: 'Move Clear lysates earlier' }));

    const titles = screen
      .getAllByRole('textbox', { name: /Step \d title/ })
      .map((input) => (input as HTMLInputElement).value);
    expect(titles).toEqual(['Clear lysates', 'Harvest treated cells']);
    expect(screen.getByLabelText('Step 1 title')).toHaveValue('Clear lysates');
  });
});

describe('ProtocolPage — calculator', () => {
  it('recalculates totals when the sample count changes', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);

    await user.type(screen.getByLabelText('Component 1 name'), 'Primary antibody');
    await user.type(screen.getByLabelText('Component 1 volume per reaction'), '5');

    await waitFor(() => expect(screen.getByTestId('mix-1-total')).toHaveTextContent('132 uL'));

    recalculate.mockResolvedValue(mixResponse('528'));
    fireEvent.change(screen.getByLabelText('Samples / wells'), { target: { value: '96' } });

    await waitFor(() => expect(screen.getByTestId('mix-1-total')).toHaveTextContent('528 uL'));
    expect(recalculate).toHaveBeenLastCalledWith(
      [
        expect.objectContaining({
          master_mix: expect.objectContaining({ reactions: 96 }),
        }),
      ],
      96,
      undefined,
    );
  });

  it('scopes the only emerald status pill to the calculator panel', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);

    await user.type(screen.getByLabelText('Component 1 name'), 'Primary antibody');
    await user.type(screen.getByLabelText('Component 1 volume per reaction'), '5');

    await waitFor(() => expect(screen.getByTestId('mix-total')).toBeInTheDocument());
    const validated = document.querySelectorAll('[data-tone="validated"]');
    expect(validated).toHaveLength(1);
    expect(validated[0]).toHaveTextContent('Arithmetic verified · this panel only');
    expect(screen.queryByText(/controls validated/i)).not.toBeInTheDocument();
  });
});

describe('ProtocolPage — controls and export', () => {
  it('shows control findings under a scope note and never as approval', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);
    await generate(user);

    expect(screen.getByText(/Controls have not been reviewed for this draft/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Review controls' }));

    expect(await screen.findByText('Loading control (GAPDH)')).toBeInTheDocument();
    expect(screen.getByText(/not validation of the protocol or its science/i)).toBeInTheDocument();
    expect(screen.getByText(/loading · not found/i)).toBeInTheDocument();
  });

  it('renders the deterministic reagent checklist with the text it was extracted from', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);
    await generate(user);

    expect(await screen.findByText('Spin speed')).toBeInTheDocument();
    expect(screen.getByText('14000 x g')).toBeInTheDocument();
    expect(screen.getByText(/“Centrifuge at 14000 x g”/)).toBeInTheDocument();
  });

  it('exports to ELN format and labels the integration as untested', async () => {
    const user = userEvent.setup();
    render(<ProtocolPage />);
    await generate(user);

    expect(screen.getByText('Untested against live API')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Benchling folder id'), 'lib_A1');
    await user.click(screen.getByRole('button', { name: 'Export to ELN format' }));

    await waitFor(() => expect(exportEln).toHaveBeenCalledWith(expect.anything(), 'lib_A1', undefined));
    const status = await screen.findByTestId('export-status');
    expect(status).toHaveTextContent('schema_ready_untested');
    expect(within(status).queryByText(/created|synced/i)).not.toBeInTheDocument();
  });

  it('surfaces a backend failure instead of showing a protocol that was not drafted', async () => {
    const user = userEvent.setup();
    draftProtocol.mockRejectedValue(new Error('drafting needs a configured model'));
    render(<ProtocolPage />);

    await user.type(screen.getByLabelText('Experimental goal'), GOAL);
    await user.click(screen.getByRole('button', { name: 'Draft protocol' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('drafting needs a configured model');
    expect(screen.queryByLabelText('Step 1 title')).not.toBeInTheDocument();
  });
});
