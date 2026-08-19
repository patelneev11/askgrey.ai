import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import { setAccessToken } from '@/lib/session';

import { REGULATORY_REVIEW_NOTICE, RegulatoryPage } from './RegulatoryPage';
import { RegulatoryProvider } from './regulatory/state';

const preclinicalReport = vi.fn();
const indStructure = vi.fn();
const indDraft = vi.fn();
const guidelineCheck = vi.fn();
const guidelineReference = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      preclinicalReport: (...args: unknown[]) => preclinicalReport(...args),
      indStructure: (...args: unknown[]) => indStructure(...args),
      indDraft: (...args: unknown[]) => indDraft(...args),
      guidelineCheck: (...args: unknown[]) => guidelineCheck(...args),
      guidelineReference: (...args: unknown[]) => guidelineReference(...args),
    },
  };
});

const NOTICE = REGULATORY_REVIEW_NOTICE;

const report = {
  study_id: 'TOX-1',
  generated_at: '2026-08-16T00:00:00Z',
  sections: [
    {
      key: 'results',
      heading: 'Results',
      text: 'The NOAEL was 30 mg/kg/day.',
      draft_status: 'first_draft',
      gaps: ['Toxicokinetic exposure margins are not reported in the submitted data.'],
      requires_expert_review: true,
      review_notice: NOTICE,
    },
  ],
  discrepancies: [
    {
      kind: 'contradicted_value' as const,
      severity: 'critical' as const,
      section: 'results',
      narrative_value: '30 mg/kg/day',
      source_value: '25 mg/kg/day',
      source_label: 'NOAEL',
      context: 'The NOAEL was 30 mg/kg/day.',
      start_char: 14,
      end_char: 26,
      explanation: 'The narrative states a NOAEL the submitted table contradicts.',
    },
  ],
  audit: {
    auditor_version: 'preclinical-audit/1',
    method: 'Exact decimal matching against the submitted study table. No language model.',
    numbers_checked: 1,
    numbers_matched: 0,
    numbers_flagged: 1,
    source_values: 3,
  },
  requires_expert_review: true,
  review_notice: NOTICE,
  drafter: 'claude',
  fixture_draft: false,
};

const structure = {
  reference: {
    version: '2026-08-16',
    retrieved: '2026-08-16',
    sources: [
      {
        id: 'M4Q(R1)',
        title: 'The CTD: Quality',
        url: 'https://database.ich.org/M4Q.pdf',
        document_date: '2002-09-12',
        covers: 'Module 3 headings',
      },
    ],
    notes: ['A heading tree is not a list of what an IND requires.'],
  },
  sections: [
    {
      id: '3.2.S.4.4',
      module: '3',
      title: 'Batch Analyses',
      requires: ['batch' as const, 'assay_result' as const],
      draftable: true,
    },
    {
      id: '3.2.R',
      module: '3',
      title: 'Regional Information',
      requires: [],
      draftable: false,
    },
  ],
  requires_expert_review: true,
  review_notice: NOTICE,
};

const draft = {
  program_name: 'AG-0412',
  generated_at: '2026-08-16T00:00:00Z',
  sections: [
    {
      section_id: '3.2.S.4.4',
      title: 'Batch Analyses',
      module: '3',
      status: 'drafted_with_gaps' as const,
      text: 'Batch AG-0412-001 assayed 99.2% by HPLC.',
      gaps: [
        {
          kind: 'missing_evidence_kind' as const,
          description: 'No specification was submitted for this section.',
          evidence_kind: 'specification' as const,
        },
      ],
      evidence_used: ['Assay purity | value: 99.2 % | batch: AG-0412-001'],
      requires_expert_completion: true,
      requires_expert_review: true,
      review_notice: NOTICE,
      source_reference: 'M4Q(R1) (2002-09-12) — https://database.ich.org/M4Q.pdf',
    },
  ],
  unknown_section_ids: [],
  unused_evidence: [],
  reference: structure.reference,
  requires_expert_review: true,
  review_notice: NOTICE,
};

const freshness = {
  version: '2026-08-16',
  retrieved: '2026-08-16',
  age_days: 12,
  review_interval_days: 90,
  stale_after_days: 180,
  review_due_on: '2026-11-14',
  stale_on: '2027-02-12',
  status: 'current' as const,
  message: 'Snapshot 2026-08-16 was read from the source documents 12 days ago (2026-08-16).',
  update_procedure: 'Refresh manually: guidelines/README.md.',
};

const staleFreshness = {
  ...freshness,
  age_days: 400,
  status: 'stale' as const,
  message: 'Snapshot 2026-08-16 was read 400 days ago, past the 180-day limit.',
};

const reference = {
  jurisdictions: [
    {
      jurisdiction: 'fda' as const,
      version: '2026-08-16',
      retrieved: '2026-08-16',
      freshness,
      notes: '',
      requirements: [
        {
          id: 'fda-batch-analyses',

          title: 'Batch analyses',
          ctd_sections: ['3.2.S.4.4'],
          citation: {
            document: '21 CFR 312.23',
            url: 'https://www.ecfr.gov/current/title-21/section-312.23',
            document_date: '2026-04-09',
          },
          expectation: 'State the analytical results for the batch used in the study.',
        },
      ],
    },
  ],
  snapshot: freshness,
  requires_expert_review: true,
  review_notice: 'Unvalidated drafting aid.',
  limitations: 'The reference data is a dated snapshot.',
};

const checkReport = {
  section_id: '3.2.S.4.4',
  word_count: 42,
  min_words_to_judge: 25,
  jurisdictions: [
    {
      jurisdiction: 'fda' as const,
      version: '2026-08-16',
      retrieved: '2026-08-16',
      freshness,
      findings: [
        {
          requirement_id: 'fda-batch-analyses',
          title: 'Batch analyses',
          ctd_sections: ['3.2.S.4.4'],
          matched_scope: '3.2.S.4.4',
          citation: reference.jurisdictions[0].requirements[0].citation,
          expectation: 'State the analytical results for the batch used in the study.',
          status: 'addressed' as const,
          explanation: 'A batch identifier and an assay result were both found.',
        },
        {
          requirement_id: 'fda-stability',
          title: 'Stability data',
          ctd_sections: ['3.2.S.7'],
          matched_scope: '',
          citation: reference.jurisdictions[0].requirements[0].citation,
          expectation: 'State the available stability data.',
          status: 'missing' as const,
          explanation: 'No phrase the engine looks for was found.',
        },
        {
          requirement_id: 'fda-method-validation',
          title: 'Method validation',
          ctd_sections: ['3.2.S.4.3'],
          matched_scope: '',
          citation: reference.jurisdictions[0].requirements[0].citation,
          expectation: 'State how the analytical method was validated.',
          status: 'indeterminate' as const,
          explanation: 'Placeholder text makes a positive match untrustworthy.',
        },
      ],
      out_of_scope_requirement_ids: ['fda-container-closure'],
    },
  ],
  snapshot: freshness,
  requires_expert_review: true,
  review_notice: 'Unvalidated drafting aid.',
  limitations: 'The reference data is a dated snapshot.',
};

/**
 * The inactive sub-features stay in the DOM (so entered data survives a tab switch), so every
 * query is scoped to the visible region rather than trusting a bare label lookup.
 */
function region(name: string) {
  return within(screen.getByRole('region', { name }));
}

/** The tab's state lives in the provider the app mounts above the router. */
function renderRegulatory() {
  return render(
    <RegulatoryProvider>
      <RegulatoryPage />
    </RegulatoryProvider>,
  );
}

beforeEach(() => {
  setAccessToken('token-123');
  indStructure.mockResolvedValue(structure);
  guidelineReference.mockResolvedValue(reference);
  preclinicalReport.mockResolvedValue(report);
  indDraft.mockResolvedValue(draft);
  guidelineCheck.mockResolvedValue(checkReport);
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

describe('Regulatory · preclinical', () => {
  it('sends the entered study table and shows the audit flags beside the draft', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    const inputs = region('Preclinical inputs');
    await user.type(inputs.getByLabelText('Study id'), 'TOX-1');
    await user.type(inputs.getByLabelText('Name'), 'NOAEL');
    await user.type(inputs.getAllByLabelText('Value')[1], '25');
    await user.type(inputs.getAllByLabelText('Unit')[1], 'mg/kg/day');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));

    await waitFor(() => expect(preclinicalReport).toHaveBeenCalledTimes(1));
    const [table, token] = preclinicalReport.mock.calls[0];
    expect(token).toBe('token-123');
    expect(table).toMatchObject({
      study_id: 'TOX-1',
      measurements: [{ name: 'NOAEL', quantity: { value: '25', unit: 'mg/kg/day' } }],
    });
    // Blank rows are dropped rather than sent as empty records.
    expect(table.groups).toEqual([]);

    const output = region('Preclinical output');
    expect(await output.findByText('Results')).toBeInTheDocument();
    expect(output.getByText(/contradicted value/)).toBeInTheDocument();
    expect(
      output.getByText(/The narrative states a NOAEL the submitted table contradicts\./),
    ).toBeInTheDocument();
    // The gap the drafter stated, rather than a filled-in plausible value.
    expect(output.getByText(/Toxicokinetic exposure margins are not reported/)).toBeInTheDocument();
    // The notice the service attached to the section, not one the UI invented.
    expect(output.getAllByText(NOTICE).length).toBeGreaterThan(0);
  });

  it('marks a fixture draft as fixture output rather than showing it as a draft', async () => {
    // The backend's development-only fixture drafter writes wrong numbers on purpose, which is
    // the only way the flagged view is reachable through the running app.
    preclinicalReport.mockResolvedValue({
      ...report,
      drafter: 'fixture-contradiction',
      fixture_draft: true,
    });
    const user = userEvent.setup();
    renderRegulatory();

    const inputs = region('Preclinical inputs');
    await user.type(inputs.getByLabelText('Study id'), 'TOX-1');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));

    const output = region('Preclinical output');
    expect(await output.findByText(/Fixture output, not a draft/)).toBeInTheDocument();
    expect(output.getByText(/deliberately incorrect numbers/)).toBeInTheDocument();
    expect(output.getByText(/fixture-contradiction/)).toBeInTheDocument();
    // The flags it exists to surface are still rendered.
    expect(output.getByText(/contradicted value/)).toBeInTheDocument();
  });

  it('does not call a model-drafted report fixture output', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    const inputs = region('Preclinical inputs');
    await user.type(inputs.getByLabelText('Study id'), 'TOX-1');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));

    const output = region('Preclinical output');
    expect(await output.findByText('Results')).toBeInTheDocument();
    expect(output.queryByText(/Fixture output/)).not.toBeInTheDocument();
  });

  it('shows a safe message when the draft fails and keeps the warning on screen', async () => {
    preclinicalReport.mockRejectedValue(new ApiError('drafting the narrative failed', 502));
    const user = userEvent.setup();
    renderRegulatory();

    const inputs = region('Preclinical inputs');
    await user.type(inputs.getByLabelText('Study id'), 'TOX-1');
    await user.click(inputs.getByRole('button', { name: 'Draft narrative and audit numbers' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('drafting the narrative failed');
    expect(screen.getAllByRole('note')).toHaveLength(2);
  });
});

describe('Regulatory · IND', () => {
  it('offers only draftable headings from the dated tree and shows gaps per section', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    await user.click(screen.getByRole('tab', { name: 'IND module 3 / 4' }));
    const inputs = region('IND inputs');

    const batchAnalyses = await inputs.findByRole('checkbox', {
      name: /3\.2\.S\.4\.4/,
    });
    expect(inputs.getByRole('checkbox', { name: /3\.2\.R/ })).toBeDisabled();

    await user.type(inputs.getByLabelText('Programme'), 'AG-0412');
    await user.click(batchAnalyses);
    await user.type(inputs.getAllByLabelText('Label')[0], 'Assay purity');
    await user.type(inputs.getAllByLabelText('Value')[0], '99.2');
    await user.click(inputs.getByRole('button', { name: 'Draft selected sections' }));

    await waitFor(() => expect(indDraft).toHaveBeenCalledTimes(1));
    expect(indDraft.mock.calls[0][0]).toMatchObject({
      program_name: 'AG-0412',
      section_ids: ['3.2.S.4.4'],
      evidence: [{ kind: 'assay_result', label: 'Assay purity', value: '99.2' }],
    });

    const output = region('IND output');
    expect(await output.findByText(/Batch Analyses/)).toBeInTheDocument();
    expect(
      output.getByText('No specification was submitted for this section.'),
    ).toBeInTheDocument();
    expect(output.getByText(/Heading source: M4Q\(R1\)/)).toBeInTheDocument();
  });
});

describe('Regulatory · guidelines', () => {
  it('checks a drafted section and groups findings by status per jurisdiction', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));
    const inputs = region('Guideline inputs');

    await waitFor(() => expect(inputs.getByRole('checkbox', { name: /FDA/ })).toBeInTheDocument());
    await user.type(inputs.getByLabelText('Section id'), '3.2.S.4.4');
    await user.type(
      inputs.getByLabelText('Draft section text'),
      'Batch AG-0412-001 assayed 99.2%.',
    );
    await user.click(inputs.getByRole('button', { name: 'Compare against jurisdictions' }));

    await waitFor(() => expect(guidelineCheck).toHaveBeenCalledTimes(1));
    expect(guidelineCheck.mock.calls[0][0]).toEqual({
      section_id: '3.2.S.4.4',
      draft_text: 'Batch AG-0412-001 assayed 99.2%.',
      jurisdictions: ['fda', 'ema', 'pmda'],
    });

    const output = region('Guideline output');
    expect(await output.findByText('FDA')).toBeInTheDocument();
    expect(output.getByText('1 addressed')).toBeInTheDocument();
    expect(output.getByText('1 missing')).toBeInTheDocument();
    expect(output.getByText('1 indeterminate')).toBeInTheDocument();
    expect(output.getByText(/scoped to other sections: fda-container-closure/)).toBeInTheDocument();
    // The engine's own limitation statement travels with the report and is shown.
    expect(output.getByText('The reference data is a dated snapshot.')).toBeInTheDocument();
  });

  // The snapshot's age is the shelf life of every finding, so it is stated before a check is run
  // and again beside the results.
  it('states how old the reference snapshot is on the form and on the report', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));
    const inputs = region('Guideline inputs');
    expect(await inputs.findByRole('status')).toHaveTextContent(
      /Reference snapshot current · 12 days old/,
    );

    await user.type(inputs.getByLabelText('Section id'), '3.2.S.4.4');
    await user.type(inputs.getByLabelText('Draft section text'), 'Batch AG-0412-001.');
    await user.click(inputs.getByRole('button', { name: 'Compare against jurisdictions' }));

    const output = region('Guideline output');
    expect(await output.findByRole('status')).toHaveTextContent(/12 days old/);
    expect(output.getByText(/2026-08-16 · 12 days old · current/)).toBeInTheDocument();
  });

  it('warns loudly and says where to refresh when the snapshot is stale', async () => {
    const user = userEvent.setup();
    guidelineReference.mockResolvedValue({ ...reference, snapshot: staleFreshness });
    guidelineCheck.mockResolvedValue({ ...checkReport, snapshot: staleFreshness });
    renderRegulatory();

    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));
    const inputs = region('Guideline inputs');
    const warning = await inputs.findByRole('alert');
    expect(warning).toHaveTextContent(/Reference snapshot stale · 400 days old/);
    expect(warning).toHaveTextContent('past the 180-day limit');
    expect(warning).toHaveTextContent('Refresh manually: guidelines/README.md.');
  });

  it('can check a section drafted elsewhere in the tab without retyping it', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    await user.click(screen.getByRole('tab', { name: 'IND module 3 / 4' }));
    let inputs = region('IND inputs');
    await user.type(inputs.getByLabelText('Programme'), 'AG-0412');
    await user.click(await inputs.findByRole('checkbox', { name: /3\.2\.S\.4\.4/ }));
    await user.type(inputs.getAllByLabelText('Label')[0], 'Assay purity');
    await user.click(inputs.getByRole('button', { name: 'Draft selected sections' }));
    await waitFor(() => expect(indDraft).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));
    inputs = region('Guideline inputs');
    await user.selectOptions(
      inputs.getByLabelText('Load a section drafted in this tab'),
      '3.2.S.4.4',
    );
    await user.click(inputs.getByRole('button', { name: 'Compare against jurisdictions' }));

    await waitFor(() => expect(guidelineCheck).toHaveBeenCalledTimes(1));
    expect(guidelineCheck.mock.calls[0][0]).toMatchObject({
      section_id: '3.2.S.4.4',
      draft_text: 'Batch AG-0412-001 assayed 99.2% by HPLC.',
    });
  });

  it('keeps entered data when switching between the sub-features', async () => {
    const user = userEvent.setup();
    renderRegulatory();

    await user.type(region('Preclinical inputs').getByLabelText('Study id'), 'TOX-1');
    await user.click(screen.getByRole('tab', { name: 'Guideline check' }));
    await user.click(screen.getByRole('tab', { name: 'Preclinical report' }));

    expect(region('Preclinical inputs').getByLabelText('Study id')).toHaveValue('TOX-1');
  });
});
