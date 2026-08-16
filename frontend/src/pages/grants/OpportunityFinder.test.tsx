import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import type { GrantOpportunity, GrantPage, MatchResult } from '@/lib/grants';
import { setAccessToken } from '@/lib/session';

import { OpportunityFinder } from './OpportunityFinder';

const searchGrants = vi.fn();
const matchGrants = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      searchGrants: (...args: unknown[]) => searchGrants(...args),
      matchGrants: (...args: unknown[]) => matchGrants(...args),
    },
  };
});

function opportunity(overrides: Partial<GrantOpportunity> = {}): GrantOpportunity {
  return {
    source: 'grants_gov',
    opportunity_id: '350001',
    number: 'PA-24-118',
    title: 'SBIR (R43/R44) — metabolic disease therapeutics',
    agency: 'NIH',
    agency_code: 'HHS-NIH-NIDDK',
    branch: 'NIDDK',
    program: 'SBIR',
    program_provenance: 'inferred',
    status: 'open',
    posted_date: '2026-01-05',
    close_date: '2026-09-05',
    funding_ceiling: 2300000,
    funding_floor: null,
    topic_description: 'Therapeutics for metabolic disease.',
    topics: [],
    url: 'https://grants.gov/opportunity/350001',
    ...overrides,
  };
}

function page(overrides: Partial<GrantPage> = {}): GrantPage {
  return {
    opportunities: [opportunity()],
    total_count: 41,
    page: 0,
    page_size: 25,
    sources: [
      { source: 'grants_gov', ok: true, total_count: 41, returned: 1, error: '' },
      { source: 'sbir', ok: false, total_count: 0, returned: 0, error: 'HTTP 403 from SBIR.gov' },
    ],
    ...overrides,
  };
}

function matchResult(overrides: Partial<MatchResult> = {}): MatchResult {
  return {
    focus: 'GLP-1 co-agonists',
    matcher: 'claude',
    candidates_considered: 12,
    matches: [
      {
        opportunity: opportunity(),
        score: 0.92,
        rationale: 'The topic names metabolic disease therapeutics explicitly.',
        matched_terms: ['metabolic disease'],
      },
    ],
    sources: [{ source: 'grants_gov', ok: true, total_count: 41, returned: 12, error: '' }],
    ...overrides,
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  searchGrants.mockReset();
  matchGrants.mockReset();
  searchGrants.mockResolvedValue(page());
  matchGrants.mockResolvedValue(matchResult());
});

describe('opportunity search', () => {
  it('shows nothing until a provider has answered', () => {
    render(<OpportunityFinder />);

    expect(screen.getByText('No search run yet')).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('searches with the filters the user set and renders the response', async () => {
    const user = userEvent.setup();
    render(<OpportunityFinder />);

    await user.type(screen.getByLabelText('Topic keyword'), 'metabolic');
    await user.type(screen.getByLabelText('Agency'), 'NIH');
    await user.selectOptions(screen.getByLabelText('Set-aside'), 'SBIR');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchGrants).toHaveBeenCalledTimes(1));
    expect(searchGrants.mock.calls[0][0]).toMatchObject({
      keyword: 'metabolic',
      agency: 'NIH',
      program: 'SBIR',
      open_only: true,
    });
    expect(
      await screen.findByText('SBIR (R43/R44) — metabolic disease therapeutics'),
    ).toBeInTheDocument();
    // Counts and deadlines are read off the response, never invented.
    expect(screen.getByText('1 shown of 41 matching')).toBeInTheDocument();
    expect(screen.getByText('2026-09-05')).toBeInTheDocument();
    expect(screen.getByText('$2,300,000')).toBeInTheDocument();
  });

  it('names the provider that failed rather than quietly dropping it', async () => {
    const user = userEvent.setup();
    render(<OpportunityFinder />);

    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(
      await screen.findByText(/SBIR\.gov unavailable · HTTP 403 from SBIR\.gov/),
    ).toBeInTheDocument();
    expect(screen.getByText(/grants\.gov · 1 of 41/)).toBeInTheDocument();
    expect(
      screen.getByText(/only carried by SBIR\.gov are missing from this result set/),
    ).toBeInTheDocument();
  });

  it('marks a grants.gov set-aside as inferred and an SBIR.gov one as stated', async () => {
    const user = userEvent.setup();
    searchGrants.mockResolvedValue(
      page({
        opportunities: [
          opportunity(),
          opportunity({
            source: 'sbir',
            opportunity_id: 'DE-FOA-1',
            program: 'STTR',
            program_provenance: 'stated',
          }),
        ],
      }),
    );
    render(<OpportunityFinder />);

    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('SBIR (inferred from title)')).toBeInTheDocument();
    expect(screen.getByText('STTR', { selector: 'dd' })).toBeInTheDocument();
  });

  it('does not claim a fit score for an unranked search', async () => {
    const user = userEvent.setup();
    render(<OpportunityFinder />);

    await user.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText('SBIR (R43/R44) — metabolic disease therapeutics');

    expect(screen.queryByText(/predicted fit/)).not.toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('ranks by focus and marks the scores as unvalidated model output', async () => {
    const user = userEvent.setup();
    render(<OpportunityFinder />);

    await user.type(screen.getByLabelText(/Research focus/), 'GLP-1 co-agonists');
    await user.click(screen.getByRole('button', { name: 'Search and rank by focus' }));

    await waitFor(() => expect(matchGrants).toHaveBeenCalledTimes(1));
    expect(matchGrants.mock.calls[0][0]).toBe('GLP-1 co-agonists');
    expect(await screen.findByText('92% predicted fit')).toBeInTheDocument();
    expect(screen.getByText('1 ranked of 12 considered')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(
      /Unvalidated prediction.*produced by a language model/i,
    );
    expect(searchGrants).not.toHaveBeenCalled();
  });

  it('does not attribute a keyword ranking to a language model', async () => {
    const user = userEvent.setup();
    matchGrants.mockResolvedValue(matchResult({ matcher: 'lexical' }));
    render(<OpportunityFinder />);

    await user.type(screen.getByLabelText(/Research focus/), 'GLP-1 co-agonists');
    await user.click(screen.getByRole('button', { name: 'Search and rank by focus' }));

    expect(await screen.findByText('92% term overlap')).toBeInTheDocument();
    expect(screen.queryByText(/predicted fit/)).not.toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(
      /Keyword ranking, not a semantic match.*because none is configured/is,
    );
  });

  it('says so when the model call failed and the keyword ranker stood in', async () => {
    const user = userEvent.setup();
    matchGrants.mockResolvedValue(matchResult({ matcher: 'claude+lexical' }));
    render(<OpportunityFinder />);

    await user.type(screen.getByLabelText(/Research focus/), 'GLP-1 co-agonists');
    await user.click(screen.getByRole('button', { name: 'Search and rank by focus' }));

    expect(await screen.findByText('92% term overlap')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(/because the model call failed/i);
  });

  it('reports a failed search instead of showing stale or invented results', async () => {
    const user = userEvent.setup();
    searchGrants.mockRejectedValue(new ApiError('grants request failed: timeout', 502));
    render(<OpportunityFinder />);

    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('grants request failed: timeout');
    expect(screen.getByText('No search run yet')).toBeInTheDocument();
  });

  it('says so when the providers return nothing', async () => {
    const user = userEvent.setup();
    searchGrants.mockResolvedValue(page({ opportunities: [], total_count: 0 }));
    render(<OpportunityFinder />);

    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('No opportunities matched those filters')).toBeInTheDocument();
  });
});
