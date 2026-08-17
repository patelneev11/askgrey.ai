import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import type { EligibilityReport } from '@/lib/grants';
import { setAccessToken } from '@/lib/session';

import { EligibilityChecklist } from './EligibilityChecklist';

const checkEligibility = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: { checkEligibility: (...args: unknown[]) => checkEligibility(...args) },
  };
});

function report(overrides: Partial<EligibilityReport> = {}): EligibilityReport {
  return {
    program: 'SBIR',
    phase: 'phase_i',
    config_version: '2026.02-sba-baseline',
    verdict: 'needs_review',
    summary: 'No SBIR rule is failed, but 1 needs review before relying on this: topic fit.',
    outcomes: [
      {
        rule_id: 'size_standard',
        title: 'Small business size standard',
        verdict: 'pass',
        explanation: '12 employees is within the 500-employee limit, counting affiliates.',
        citation: '13 CFR 121.702(c)',
        missing_fields: [],
      },
      {
        rule_id: 'us_ownership',
        title: 'US ownership',
        verdict: 'needs_review',
        explanation: 'Ownership percentages are not recorded, so this cannot be decided.',
        citation: '13 CFR 121.702(a)',
        missing_fields: ['ownership.us_individuals_percent'],
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  checkEligibility.mockReset();
  checkEligibility.mockResolvedValue(report());
});

describe('eligibility checklist', () => {
  it('keeps the legal caveat visible before anything is checked', () => {
    render(<EligibilityChecklist />);

    expect(screen.getByRole('note')).toHaveTextContent(/Not a legal determination/i);
    expect(screen.getByText('No profile checked yet')).toBeInTheDocument();
  });

  it('sends the structured profile and renders a verdict per rule', async () => {
    const user = userEvent.setup();
    render(<EligibilityChecklist />);

    await user.type(screen.getByLabelText('Employees (including affiliates)'), '12');
    await user.selectOptions(screen.getByLabelText('Organization type'), 'for_profit');
    await user.click(screen.getByRole('button', { name: 'Check eligibility' }));

    await waitFor(() => expect(checkEligibility).toHaveBeenCalledTimes(1));
    expect(checkEligibility.mock.calls[0][0]).toMatchObject({
      employee_count: 12,
      organization_type: 'for_profit',
    });
    expect(checkEligibility.mock.calls[0][1]).toBe('SBIR');

    expect(await screen.findByText('Small business size standard')).toBeInTheDocument();
    expect(screen.getByText('13 CFR 121.702(c)')).toBeInTheDocument();
    expect(screen.getAllByText('Pass')).toHaveLength(1);
    expect(screen.getByText(/No SBIR rule is failed/)).toBeInTheDocument();
    expect(screen.getByText('Rule set 2026.02-sba-baseline')).toBeInTheDocument();
  });

  it('leaves unanswered facts unset rather than sending zero', async () => {
    const user = userEvent.setup();
    render(<EligibilityChecklist />);

    await user.click(screen.getByRole('button', { name: 'Check eligibility' }));

    await waitFor(() => expect(checkEligibility).toHaveBeenCalledTimes(1));
    expect(checkEligibility.mock.calls[0][0]).toMatchObject({
      employee_count: null,
      principal_place_of_business_us: null,
      ownership: { us_individuals_percent: null },
    });
  });

  it('names the field a rule is missing', async () => {
    const user = userEvent.setup();
    render(<EligibilityChecklist />);

    await user.click(screen.getByRole('button', { name: 'Check eligibility' }));

    expect(
      await screen.findByText('Missing: ownership.us_individuals_percent'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0);
  });

  it('reports the server error and shows no verdict', async () => {
    const user = userEvent.setup();
    checkEligibility.mockRejectedValue(new ApiError('no SBIR rules are enabled', 422));
    render(<EligibilityChecklist />);

    await user.click(screen.getByRole('button', { name: 'Check eligibility' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('no SBIR rules are enabled');
    expect(screen.getByText('No profile checked yet')).toBeInTheDocument();
  });
});
