import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { ProtocolPage } from './ProtocolPage';
import { RegulatoryPage } from './RegulatoryPage';
import { TermsPage } from './TermsPage';
import { RegulatoryProvider } from './regulatory/state';

// Regulatory loads its CTD heading tree and guideline reference vintages on mount, and the terms
// page reads the published version; this suite is about what the pages say, so those calls are
// stubbed rather than reaching fetch.
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      indStructure: () => new Promise(() => {}),
      guidelineReference: () => new Promise(() => {}),
      terms: () => Promise.resolve({ version: '2026-09-06' }),
    },
  };
});

// Where the product's limits are stated is a product requirement, not decoration: they used to be
// an amber warning band on top of every tab, which is how a caveat stops being read. The full
// statement now lives in the terms of agreement each account accepts on registration, and the two
// outputs that would otherwise read as measurements — an extracted value and a prediction — keep
// one small line of text beside them (asserted in LiteraturePage.test.tsx and
// ScreeningPage.test.tsx, over their live payloads).
describe('where the product states its limits', () => {
  it('states the drafting, prediction and legal limits in the terms of agreement', () => {
    render(
      <MemoryRouter>
        <TermsPage />
      </MemoryRouter>,
    );

    const terms = screen.getByRole('article');
    expect(terms).toHaveTextContent(/not a medical device/i);
    expect(terms).toHaveTextContent(/extracted by a language model/i);
    expect(terms).toHaveTextContent(/computational predictions/i);
    expect(terms).toHaveTextContent(/absence is not evidence of safety/i);
    expect(terms).toHaveTextContent(/requires review by a qualified researcher/i);
    expect(terms).toHaveTextContent(/not a legal determination/i);
    expect(terms).toHaveTextContent(/not freedom to operate/i);
    expect(terms).toHaveTextContent(/not calibrated against real NIH or SBIR reviewer scores/i);
    expect(terms).toHaveTextContent(/may not upload protected health information/i);
  });

  // Protocol and Regulatory draft prose a human reads in full, so a standing warning above it was
  // pure furniture: the requirement to have it reviewed is in the terms, and the pane keeps the
  // space for the draft.
  it('does not repeat a standing warning over the Protocol and Regulatory drafts', () => {
    render(<ProtocolPage />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();

    render(
      <RegulatoryProvider>
        <RegulatoryPage />
      </RegulatoryProvider>,
    );
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
