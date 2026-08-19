import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '@/lib/session';

import { REGULATORY_REVIEW_NOTICE, RegulatoryPage } from './RegulatoryPage';
import { RegulatoryProvider } from './regulatory/state';

const preclinicalReport = vi.fn();
const indStructure = vi.fn();
const guidelineReference = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      preclinicalReport: (...args: unknown[]) => preclinicalReport(...args),
      indStructure: (...args: unknown[]) => indStructure(...args),
      guidelineReference: (...args: unknown[]) => guidelineReference(...args),
    },
  };
});

const report = {
  study_id: 'TOX-2026-777',
  generated_at: '2026-08-16T00:00:00Z',
  sections: [
    {
      key: 'results',
      heading: 'Results',
      text: 'The NOAEL was 25 mg/kg/day.',
      draft_status: 'first_draft',
      gaps: [],
      requires_expert_review: true,
      review_notice: REGULATORY_REVIEW_NOTICE,
    },
  ],
  discrepancies: [],
  audit: {
    auditor_version: 'preclinical-audit/1',
    method: 'Exact decimal matching against the submitted study table. No language model.',
    numbers_checked: 1,
    numbers_matched: 1,
    numbers_flagged: 0,
    source_values: 1,
  },
  requires_expert_review: true,
  review_notice: REGULATORY_REVIEW_NOTICE,
  drafter: 'claude',
  fixture_draft: false,
};

/** The app mounts the provider above the router; the route itself is free to unmount. */
function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/regulatory']}>
      <RegulatoryProvider>
        <nav>
          <Link to="/regulatory">Regulatory</Link>
          <Link to="/literature">Literature</Link>
        </nav>
        <Routes>
          <Route path="/regulatory" element={<RegulatoryPage />} />
          <Route path="/literature" element={<h1>Literature</h1>} />
        </Routes>
      </RegulatoryProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  setAccessToken('token-123');
  indStructure.mockReturnValue(new Promise(() => {}));
  guidelineReference.mockReturnValue(new Promise(() => {}));
  preclinicalReport.mockResolvedValue(report);
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

// A drafted narrative costs a model call and the study record costs a researcher's typing; losing
// either to a click on another sidebar tab is data loss, not a cosmetic reset.
describe('Regulatory state across route navigation', () => {
  it('keeps entered inputs and the drafted narrative when the route unmounts and returns', async () => {
    const user = userEvent.setup();
    renderShell();

    const inputs = within(screen.getByRole('region', { name: 'Preclinical inputs' }));
    await user.type(inputs.getByLabelText('Study id'), 'TOX-2026-777');
    await user.type(inputs.getByLabelText('Name'), 'NOAEL');
    await user.type(inputs.getAllByLabelText('Value')[1], '25');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));
    await waitFor(() => expect(preclinicalReport).toHaveBeenCalledTimes(1));
    expect(screen.getByText('The NOAEL was 25 mg/kg/day.')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Literature' }));
    expect(screen.getByRole('heading', { name: 'Literature' })).toBeInTheDocument();
    expect(screen.queryByText('The NOAEL was 25 mg/kg/day.')).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Regulatory' }));

    const returned = within(screen.getByRole('region', { name: 'Preclinical inputs' }));
    expect(returned.getByLabelText('Study id')).toHaveValue('TOX-2026-777');
    expect(screen.getByText('The NOAEL was 25 mg/kg/day.')).toBeInTheDocument();
    // Re-mounting must not silently re-run the model call that produced the draft.
    expect(preclinicalReport).toHaveBeenCalledTimes(1);
  });

  it('still offers the drafted section to the guideline check after navigating away', async () => {
    const user = userEvent.setup();
    renderShell();

    const inputs = within(screen.getByRole('region', { name: 'Preclinical inputs' }));
    await user.type(inputs.getByLabelText('Study id'), 'TOX-2026-777');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));
    await waitFor(() => expect(preclinicalReport).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('link', { name: 'Literature' }));
    await user.click(screen.getByRole('link', { name: 'Regulatory' }));
    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));

    const guidelines = within(screen.getByRole('region', { name: 'Guideline inputs' }));
    expect(
      guidelines.getByRole('option', { name: 'Preclinical · Results' }),
    ).toBeInTheDocument();
  });

  it('loads the reference data once, on the first visit to the tab', async () => {
    const user = userEvent.setup();
    renderShell();

    await waitFor(() => expect(indStructure).toHaveBeenCalledTimes(1));
    expect(guidelineReference).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('link', { name: 'Literature' }));
    await user.click(screen.getByRole('link', { name: 'Regulatory' }));

    expect(indStructure).toHaveBeenCalledTimes(1);
    expect(guidelineReference).toHaveBeenCalledTimes(1);
  });
});
