import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import { setAccessToken } from '@/lib/session';
import { admetProfile, descriptorProfile, patentLandscape, suggestionSet } from '@/test/fixtures';

import { ScreeningPage } from './ScreeningPage';

const screeningDescriptors = vi.fn();
const screeningAdmet = vi.fn();
const screeningSuggestions = vi.fn();
const screeningPatents = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      screeningDescriptors: (...args: unknown[]) => screeningDescriptors(...args),
      screeningAdmet: (...args: unknown[]) => screeningAdmet(...args),
      screeningSuggestions: (...args: unknown[]) => screeningSuggestions(...args),
      screeningPatents: (...args: unknown[]) => screeningPatents(...args),
    },
  };
});

const TERFENADINE = 'CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1';

beforeEach(() => {
  setAccessToken('token-123');
  screeningDescriptors.mockResolvedValue(descriptorProfile());
  screeningAdmet.mockResolvedValue(admetProfile());
  screeningSuggestions.mockResolvedValue(suggestionSet());
  screeningPatents.mockResolvedValue(patentLandscape());
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
});

async function profile(user: ReturnType<typeof userEvent.setup>, smiles = TERFENADINE) {
  await user.type(screen.getByLabelText('SMILES'), smiles);
  await user.click(screen.getByRole('button', { name: 'Profile structure' }));
  await waitFor(() => expect(screen.getByText('Identity')).toBeInTheDocument());
}

describe('the SMILES input flow', () => {
  it('profiles the structure the researcher typed and renders the real payload', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);

    expect(screen.getByText('No structure profiled yet')).toBeInTheDocument();
    await profile(user);

    expect(screeningDescriptors).toHaveBeenCalledWith(TERFENADINE, 'token-123');
    expect(screeningAdmet).toHaveBeenCalledWith(TERFENADINE, 'token-123');
    // Values come from the response, not from anything hard-coded in the page.
    expect(screen.getAllByText('471.69 g/mol').length).toBeGreaterThan(0);
    expect(screen.getAllByText('C32H41NO2').length).toBeGreaterThan(0);
    expect(screen.getByText(/Lipinski's rule of five/)).toBeInTheDocument();
  });

  it('loads an example structure and profiles it in one click', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);

    await user.click(screen.getByRole('button', { name: /Aspirin/ }));

    await waitFor(() =>
      expect(screeningDescriptors).toHaveBeenCalledWith('CC(=O)OC1=CC=CC=C1C(=O)O', 'token-123'),
    );
  });

  it('does not call the backend for an empty box', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);

    await user.click(screen.getByRole('button', { name: 'Profile structure' }));

    expect(screeningDescriptors).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a SMILES string');
  });

  it("surfaces the server's rejection of a malformed structure", async () => {
    screeningDescriptors.mockRejectedValue(
      new ApiError("'not a molecule' is not a valid SMILES string.", 422),
    );
    const user = userEvent.setup();
    render(<ScreeningPage />);

    await user.type(screen.getByLabelText('SMILES'), 'not a molecule');
    await user.click(screen.getByRole('button', { name: 'Profile structure' }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('not a valid SMILES string'),
    );
    expect(screen.getByText('No structure profiled yet')).toBeInTheDocument();
  });
});

// The caveats are the blocking requirement for this tab: a regression that drops one is a
// correctness bug, so each is asserted against the rendered DOM rather than the payload.
describe('caveats and provenance in the DOM', () => {
  it('keeps a standing caveat band above the results and one on each predicted section', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    const bands = screen.getAllByRole('note');
    expect(bands.length).toBeGreaterThanOrEqual(3);
    expect(bands[0]).toHaveTextContent(
      /computational approximations \(RDKit\/LLM\).*not validated assay results/i,
    );
    expect(bands.some((band) => /not evidence that this compound has the liability/i.test(band.textContent ?? ''))).toBe(
      true,
    );
    expect(bands.some((band) => /not measured, not fitted to this compound/i.test(band.textContent ?? ''))).toBe(
      true,
    );
  });

  it('renders the model basis for every ADMET estimate, unavailable ones included', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    const bases = screen.getAllByText('Model basis');
    // One per estimate (3 in the fixture) plus one per liability flag.
    expect(bases.length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/Egan's physicochemical delineation/)).toBeInTheDocument();
    expect(screen.getAllByText(/Published hERG pharmacophore features/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Published PPB models are regressions on measured fu/)).toBeInTheDocument();
  });

  it('marks predicted headline values inline so a cropped screenshot keeps the label', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    expect(screen.getAllByText('predicted').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Inside the Egan well-absorbed region \(predicted\)/)).toBeInTheDocument();
  });

  it('states unavailable properties instead of showing a plausible number', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    expect(screen.getByText('Plasma protein binding')).toBeInTheDocument();
    expect(screen.getByText(/no fabricated value is shown here/i)).toBeInTheDocument();
    expect(screen.getByText(/A validated QSAR trained on measured fu/)).toBeInTheDocument();
    expect(screen.getByText(/Binding affinity: unavailable/)).toBeInTheDocument();
  });
});

describe('toxicity and liability visibility', () => {
  it('renders the liability section before the ADMET section in the document', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    const liabilities = screen.getByText('Toxicity & liability flags');
    const admet = screen.getByText('ADMET prediction');
    expect(liabilities.compareDocumentPosition(admet)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('summarises the flag count in the header and anchors it to the section', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '#screening-liabilities');
    expect(link).toHaveTextContent('2 liability flags');
  });

  it('lists both the unfavourable rule outcome and the matched structural alert', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    const section = screen.getByText('Toxicity & liability flags').closest('section');
    expect(section).not.toBeNull();
    const flags = within(section as HTMLElement).getAllByRole('listitem');
    expect(flags).toHaveLength(2);
    expect(flags[0]).toHaveTextContent(/hERG liability — Matches the basic-amine/);
    expect(flags[1]).toHaveTextContent(/Basic amine with lipophilic aromatic character/);
    // The unmatched alert is not presented as a finding.
    expect(within(section as HTMLElement).queryByText(/Furan/)).not.toBeInTheDocument();
  });

  it('says an empty flag list is not a safety assessment', async () => {
    screeningAdmet.mockResolvedValue(
      admetProfile({
        estimates: [admetProfile().estimates[0]],
        alerts: admetProfile().alerts.map((alert) => ({ ...alert, matched: false })),
      }),
    );
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    expect(screen.getByText(/it is not a safety assessment/i)).toBeInTheDocument();
    expect(screen.getByText('No flag from the screened list')).toBeInTheDocument();
  });
});

describe('substituent suggestions', () => {
  it('only calls the LLM-backed route on request, and labels the result unvalidated', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    expect(screeningSuggestions).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Suggest modifications' }));

    await waitFor(() =>
      expect(screen.getByText(/Replace the tert-butyl group/)).toBeInTheDocument(),
    );
    expect(screeningSuggestions).toHaveBeenCalledWith(TERFENADINE, 'token-123');
    expect(
      screen.getAllByRole('note').some((band) => /Unvalidated heuristic suggestions/.test(band.textContent ?? '')),
    ).toBe(true);
    expect(screen.getByText('heuristic')).toBeInTheDocument();
  });

  it('reports a throttled suggestion run without discarding the profile', async () => {
    screeningSuggestions.mockRejectedValue(new ApiError('Rate limit exceeded. Retry in 41s.', 429));
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    await user.click(screen.getByRole('button', { name: 'Suggest modifications' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Rate limit exceeded'));
    expect(screen.getAllByText('471.69 g/mol').length).toBeGreaterThan(0);
  });
});

describe('the patent landscape', () => {
  it('runs the keyword search on request and shows what was actually searched', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);

    expect(screeningPatents).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/keywords/i), 'antihistamine');
    await user.click(screen.getByRole('button', { name: 'Search prior art' }));

    await waitFor(() =>
      expect(screen.getByText('Piperidine derivatives useful as antihistamines')).toBeInTheDocument(),
    );
    expect(screeningPatents).toHaveBeenCalledWith(TERFENADINE, 'antihistamine', 'token-123');
    expect(screen.getByText('C32H41NO2 AND antihistamine')).toBeInTheDocument();
    expect(screen.getByText(/not on the structure itself/)).toBeInTheDocument();
    expect(screen.getByText('Showing 1 of 3 keyword matches.')).toBeInTheDocument();
  });

  it('never presents the hits as novelty or a structural search', async () => {
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);
    await user.click(screen.getByRole('button', { name: 'Search prior art' }));

    await waitFor(() => expect(screen.getByText(/Novelty score: unavailable/)).toBeInTheDocument());
    expect(
      screen.getByText(/Structural similarity \/ substructure prior-art search: unavailable/),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole('note')
        .some((band) => /not a structural similarity\s+search, not a novelty assessment/i.test(band.textContent ?? '')),
    ).toBe(true);
  });

  it('says the source was unavailable rather than letting an empty list read as no prior art', async () => {
    screeningPatents.mockResolvedValue(
      patentLandscape({
        source_available: false,
        source_status:
          'The USPTO Open Data Portal search API requires a free API key (X-API-KEY) and none is configured for this deployment, so no patent search was performed. Nothing below is a search result.',
        hits: [],
        returned: 0,
        total_found: null,
        no_match_statement: '',
      }),
    );
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);
    await user.click(screen.getByRole('button', { name: 'Search prior art' }));

    await waitFor(() => expect(screen.getByText('Source unavailable')).toBeInTheDocument());
    expect(screen.getByText(/no patent search was performed/)).toBeInTheDocument();
    expect(screen.queryByText(/keyword matches\./)).not.toBeInTheDocument();
  });

  it('spells out that no keyword match is not evidence of novelty', async () => {
    screeningPatents.mockResolvedValue(
      patentLandscape({
        hits: [],
        returned: 0,
        total_found: 0,
        no_match_statement:
          'No keyword matches found for this query. This is not evidence of novelty: prior art may exist under different wording.',
      }),
    );
    const user = userEvent.setup();
    render(<ScreeningPage />);
    await profile(user);
    await user.click(screen.getByRole('button', { name: 'Search prior art' }));

    await waitFor(() =>
      expect(screen.getByText(/This is not evidence of novelty/)).toBeInTheDocument(),
    );
  });
});
