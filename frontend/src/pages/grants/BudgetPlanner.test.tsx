import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import type { GrantBudget } from '@/lib/grants';
import { setAccessToken } from '@/lib/session';

import { BudgetPlanner } from './BudgetPlanner';

const buildBudget = vi.fn();
const exportBudget = vi.fn();
const listArtifacts = vi.fn();
const saveArtifact = vi.fn();
const loadArtifact = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      buildBudget: (...args: unknown[]) => buildBudget(...args),
      exportBudget: (...args: unknown[]) => exportBudget(...args),
      listArtifacts: (...args: unknown[]) => listArtifacts(...args),
      saveArtifact: (...args: unknown[]) => saveArtifact(...args),
      loadArtifact: (...args: unknown[]) => loadArtifact(...args),
    },
  };
});

function budget(overrides: Partial<GrantBudget> = {}): GrantBudget {
  return {
    program: 'SBIR',
    phase: 'phase_i',
    period_months: 6,
    organization: '',
    project_title: '',
    rules_version: '2026.02-federal',
    sections: [
      {
        code: 'A',
        title: 'A. Senior/Key Person',
        lines: [
          {
            label: 'Principal Investigator',
            basis: '50% effort x 6.0 months on a $120,000.00 base',
            amount: '30000.00',
            category: null,
          },
        ],
        subtotal: '30000.00',
      },
      { code: 'H', title: 'H. Indirect Costs', lines: [], subtotal: '0.00' },
    ],
    indirect_base: '30000.00',
    indirect_rate_percent: '0',
    fee_percent: '0',
    adjustments: [
      {
        rule_id: 'salary_cap',
        message: 'Base salary reduced to the $225,700.00 federal cap.',
        amount: '-1200.00',
        authority: 'NIH Grants Policy Statement',
      },
    ],
    warnings: ['No negotiated indirect rate given; the de minimis rate was used.'],
    total_direct: '30000.00',
    indirect: '0.00',
    total_direct_and_indirect: '30000.00',
    fee: '0.00',
    total: '30000.00',
    ...overrides,
  };
}

async function fillPerson(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Role 1'), 'Principal Investigator');
  await user.type(screen.getByLabelText('Base salary 1'), '120000');
  await user.type(screen.getByLabelText('Effort percent 1'), '50');
  await user.type(screen.getByLabelText('Months 1'), '6');
}

beforeEach(() => {
  setAccessToken('token-123');
  buildBudget.mockReset();
  exportBudget.mockReset();
  listArtifacts.mockReset();
  saveArtifact.mockReset();
  loadArtifact.mockReset();
  listArtifacts.mockResolvedValue([]);
  saveArtifact.mockResolvedValue({});
  buildBudget.mockResolvedValue(budget());
  exportBudget.mockResolvedValue({
    blob: new Blob(['x'], { type: 'text/csv' }),
    filename: 'grant-budget.csv',
  });
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

describe('budget builder', () => {
  it('shows no figures and no export until something is costed', () => {
    render(<BudgetPlanner />);

    expect(screen.getByText('Nothing costed yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export .xlsx' })).toBeDisabled();
    expect(screen.getByRole('note')).toHaveTextContent(/Planning figures, not a submission/i);
  });

  it('costs the lines the user entered and renders the backend totals', async () => {
    const user = userEvent.setup();
    render(<BudgetPlanner />);

    await fillPerson(user);
    await user.click(screen.getByRole('button', { name: 'Cost the budget' }));

    await waitFor(() => expect(buildBudget).toHaveBeenCalledTimes(1));
    expect(buildBudget.mock.calls[0][0]).toMatchObject({
      phase: 'phase_i',
      period_months: 6,
      personnel: [
        {
          role: 'Principal Investigator',
          base_salary_annual: '120000',
          effort_percent: '50',
          months: '6',
          fringe_rate_percent: null,
        },
      ],
      // The blank cost row is dropped rather than sent as a zero line.
      costs: [],
      indirect_rate_percent: null,
    });

    expect(await screen.findByText(/Total request over 6 months/)).toHaveTextContent(
      '$30,000 direct',
    );
    // Total and the section subtotal are both the backend's own figures, printed as given.
    expect(screen.getAllByText('$30,000')).toHaveLength(2);
    expect(screen.getByText('A. Senior/Key Person')).toBeInTheDocument();
    expect(screen.getByText('50% effort x 6.0 months on a $120,000.00 base')).toBeInTheDocument();
    expect(screen.getByText('Rules 2026.02-federal')).toBeInTheDocument();
  });

  it('shows every rule that changed a requested number, with its authority', async () => {
    const user = userEvent.setup();
    render(<BudgetPlanner />);

    await fillPerson(user);
    await user.click(screen.getByRole('button', { name: 'Cost the budget' }));

    expect(
      await screen.findByText('Base salary reduced to the $225,700.00 federal cap.'),
    ).toBeInTheDocument();
    expect(screen.getByText('NIH Grants Policy Statement')).toBeInTheDocument();
    expect(
      screen.getByText('No negotiated indirect rate given; the de minimis rate was used.'),
    ).toBeInTheDocument();
  });

  it('exports the same budget through the shared exporter', async () => {
    const user = userEvent.setup();
    render(<BudgetPlanner />);

    await fillPerson(user);
    await user.click(screen.getByRole('button', { name: 'Cost the budget' }));
    await screen.findByText(/Total request over 6 months/);
    await user.click(screen.getByRole('button', { name: 'Export .csv' }));

    await waitFor(() => expect(exportBudget).toHaveBeenCalledTimes(1));
    expect(exportBudget.mock.calls[0][1]).toBe('csv');
  });

  it('keeps a costed budget only when the researcher saves it', async () => {
    const user = userEvent.setup();
    render(<BudgetPlanner />);

    await fillPerson(user);
    await user.click(screen.getByRole('button', { name: 'Cost the budget' }));
    await screen.findByText(/Total request over 6 months/);

    // Costing a budget is not a decision to keep it.
    expect(saveArtifact).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Save to library' }));

    await waitFor(() => expect(saveArtifact).toHaveBeenCalledTimes(1));
    expect(saveArtifact.mock.calls[0][0]).toMatchObject({
      kind: 'grants_budget',
      payload: { total: '30000.00' },
    });
  });

  it('will not export a budget reopened from the library, because the form no longer holds it', async () => {
    const user = userEvent.setup();
    listArtifacts.mockResolvedValue([
      {
        id: 'artifact-1',
        kind: 'grants_budget',
        title: 'Saved budget',
        subtitle: '$30,000 over 6 months',
        created_at: '2026-08-16T00:00:00Z',
        updated_at: '2026-08-16T00:00:00Z',
      },
    ]);
    loadArtifact.mockResolvedValue({ id: 'artifact-1', payload: budget() });
    render(<BudgetPlanner />);

    await user.click(await screen.findByText('Saved budget'));

    expect(await screen.findByText(/Total request over 6 months/)).toBeInTheDocument();
    expect(screen.getByText(/Reopened from the library/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export .xlsx' })).toBeDisabled();
  });

  it('reports a rejected budget rather than showing a partial one', async () => {
    const user = userEvent.setup();
    buildBudget.mockRejectedValue(
      new ApiError('a budget needs at least one personnel or cost line', 422),
    );
    render(<BudgetPlanner />);

    await user.click(screen.getByRole('button', { name: 'Cost the budget' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'a budget needs at least one personnel or cost line',
    );
    expect(screen.getByText('Nothing costed yet')).toBeInTheDocument();
  });
});
