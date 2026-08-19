import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProtocolPage } from './ProtocolPage';
import { RegulatoryPage, REGULATORY_REVIEW_NOTICE } from './RegulatoryPage';
import { RegulatoryProvider } from './regulatory/state';

// Regulatory loads its CTD heading tree and guideline reference vintages on mount; this suite is
// about the warnings, so those calls are stubbed rather than reaching fetch.
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      indStructure: () => new Promise(() => {}),
      guidelineReference: () => new Promise(() => {}),
    },
  };
});

// These caveats are a product requirement, not decoration: the numbers on these pages are
// model output, so a regression that drops the warning is a correctness bug.
// Screening renders its caveats over a live payload, so they are asserted against the rendered
// results in ScreeningPage.test.tsx rather than here.
describe('unvalidated / draft disclaimers', () => {
  it('warns on Protocol that drafts need qualified review', () => {
    render(<ProtocolPage />);

    expect(screen.getByRole('note')).toHaveTextContent(
      /Agent-drafted content\. Requires qualified researcher review/i,
    );
  });

  // Regulatory is the highest-liability surface: the warning is asserted per pane, because a
  // reviewer reading a long draft in one pane must not be able to scroll away from it.
  it('warns in both Regulatory panes that drafts need regulatory affairs review', () => {
    render(
      <RegulatoryProvider>
        <RegulatoryPage />
      </RegulatoryProvider>,
    );

    const notes = screen.getAllByRole('note');
    expect(notes).toHaveLength(2);
    for (const note of notes) {
      expect(note).toHaveTextContent(REGULATORY_REVIEW_NOTICE);
    }
  });
});
