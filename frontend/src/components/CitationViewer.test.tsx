import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { citation, paperRow } from '@/test/fixtures';

import { CitationViewer } from './CitationViewer';

describe('CitationViewer', () => {
  it('prompts for a selection when no citation is open', () => {
    render(<CitationViewer target={null} />);
    expect(screen.getByText('No passage selected')).toBeInTheDocument();
  });

  it('shows the page anchor, the match quality and the quote for a server-fetched paper', () => {
    render(
      <CitationViewer
        target={{ row: paperRow(), columnLabel: 'sample size', citation: citation() }}
      />,
    );

    expect(screen.getByText('sample size')).toBeInTheDocument();
    expect(screen.getByText('page 4')).toBeInTheDocument();
    expect(screen.getByText('verified quote')).toBeInTheDocument();
    expect(
      screen.getByText('73 patients were randomized to ziprasidone or placebo'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open the source pdf at page 4/i })).toHaveAttribute(
      'href',
      'https://example.org/paper.pdf#page=4',
    );
  });

  it('warns when the span was only matched approximately', () => {
    render(
      <CitationViewer
        target={{
          row: paperRow(),
          columnLabel: 'sample size',
          citation: citation({ match: 'fuzzy' }),
        }}
      />,
    );

    expect(screen.getByText('approximate quote')).toBeInTheDocument();
  });

  it('renders the page itself when the PDF was uploaded in this session', () => {
    const file = new File([new Uint8Array([1, 2, 3])], 'paper.pdf', { type: 'application/pdf' });
    render(
      <CitationViewer
        target={{ row: paperRow(), columnLabel: 'sample size', citation: citation() }}
        fileFor={() => file}
      />,
    );

    // The quote fallback is replaced by the page surface and its highlight overlay.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('citation-highlight')).toHaveLength(1);
  });
});
