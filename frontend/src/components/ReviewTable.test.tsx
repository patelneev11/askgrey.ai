import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { grounded, notFound, paperRow, table, ungrounded } from '@/test/fixtures';

import { ReviewTable } from './ReviewTable';

describe('ReviewTable', () => {
  it('renders one column per requested field and one row per paper', () => {
    render(
      <ReviewTable
        table={table({
          columns: [
            { key: 'sample_size', label: 'sample size', description: '' },
            { key: 'endpoint', label: 'primary endpoint', description: '' },
          ],
          rows: [
            paperRow({
              cells: { sample_size: grounded('73 patients'), endpoint: ungrounded('YMRS change') },
            }),
            paperRow({ document_id: 'doc-2', title: 'Second trial', cells: {} }),
          ],
        })}
        onCitationSelect={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Paper',
      'sample size',
      'primary endpoint',
    ]);
    expect(screen.getByText('Ziprasidone in acute mania')).toBeInTheDocument();
    expect(screen.getByText('Second trial')).toBeInTheDocument();
  });

  it('hands the citation back when a cited value is clicked', async () => {
    const onCitationSelect = vi.fn();
    render(<ReviewTable table={table()} onCitationSelect={onCitationSelect} />);

    await userEvent.click(screen.getByRole('button', { name: /show source for/i }));

    expect(onCitationSelect).toHaveBeenCalledTimes(1);
    const [row, columnKey, cell] = onCitationSelect.mock.calls[0];
    expect(row.document_id).toBe('doc-1');
    expect(columnKey).toBe('sample_size');
    expect(cell.citation.page_number).toBe(4);
  });

  it('marks the cell whose citation is open in the viewer', () => {
    render(
      <ReviewTable table={table()} activeCell="doc-1::sample_size" onCitationSelect={vi.fn()} />,
    );

    expect(screen.getByRole('button', { name: /show source for/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('states the page in words, flagging only a genuinely approximate match', () => {
    const { rerender } = render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);
    expect(screen.getByText('page 4')).toBeInTheDocument();

    // A normalized match only folded whitespace before matching: still verified.
    rerender(
      <ReviewTable
        table={table({
          rows: [paperRow({ cells: { sample_size: grounded('73 patients', 'normalized') } })],
        })}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('page 4')).toBeInTheDocument();

    rerender(
      <ReviewTable
        table={table({
          rows: [paperRow({ cells: { sample_size: grounded('73 patients', 'fuzzy') } })],
        })}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('page 4, close wording')).toBeInTheDocument();
  });

  it('keeps the exact page, block and match-quality detail on the value as a tooltip', () => {
    render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);

    expect(screen.getByRole('button', { name: /show source for/i })).toHaveAttribute(
      'title',
      expect.stringContaining('text block p4-b2'),
    );
    expect(screen.getByRole('button', { name: /show source for/i })).toHaveAttribute(
      'title',
      expect.stringContaining('"exact" match'),
    );
  });

  it("shows the backend's note under a cited value, not only in a tooltip", () => {
    render(
      <ReviewTable
        table={table({
          rows: [
            paperRow({
              cells: {
                sample_size: {
                  ...grounded('73 patients'),
                  note: 'reported as randomised, not analysed',
                },
              },
            }),
          ],
        })}
        onCitationSelect={vi.fn()}
      />,
    );

    expect(screen.getByText('reported as randomised, not analysed')).toBeInTheDocument();
  });

  it('keeps the table overflow inside its own scroll container', () => {
    const { container } = render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);

    const scroll = container.querySelector('table')?.parentElement;
    expect(scroll).not.toBeNull();
    // The legend must sit outside the scroll box so it cannot be pushed off-screen with it.
    expect(scroll?.querySelector('details')).toBeNull();
  });

  it('surfaces an ungrounded value as untraceable rather than as a citation link', () => {
    render(
      <ReviewTable
        table={table({ rows: [paperRow({ cells: { sample_size: ungrounded('73 patients') } })] })}
        onCitationSelect={vi.fn()}
      />,
    );

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    // Once in the cell, once in the legend that explains the tag.
    expect(screen.getAllByText('no source found')).toHaveLength(2);
  });

  it('renders a missing value as a dash, not as an empty cell', () => {
    render(
      <ReviewTable
        table={table({ rows: [paperRow({ cells: { sample_size: notFound() } })] })}
        onCitationSelect={vi.fn()}
      />,
    );

    expect(screen.getByText('Not reported in this paper')).toBeInTheDocument();
  });

  it("shows the backend's note on screen when a value could not be grounded", () => {
    render(
      <ReviewTable
        table={table({ rows: [paperRow({ cells: { sample_size: ungrounded('73 patients') } })] })}
        onCitationSelect={vi.fn()}
      />,
    );

    expect(screen.getByText('quote not found in parsed text')).toBeInTheDocument();
  });

  it('renders every row warning rather than only the first', async () => {
    render(
      <ReviewTable
        table={table({
          rows: [
            paperRow({
              warnings: ['page 3 is a scanned image', 'no abstract detected'],
            }),
          ],
        })}
        onCitationSelect={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText('2 problems reading this paper'));
    expect(screen.getByText('page 3 is a scanned image')).toBeInTheDocument();
    expect(screen.getByText('no abstract detected')).toBeInTheDocument();
  });

  it('explains the result vocabulary in a legend', () => {
    render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);

    expect(screen.getByText(/the quote is on page 1 of the PDF/i)).toBeInTheDocument();
    expect(screen.getByText(/could not be traced to a passage/i)).toBeInTheDocument();
  });

  it('keeps the exact matching vocabulary available as an expandable detail', async () => {
    render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);

    await userEvent.click(screen.getByText(/how a quote is matched to a page/i));
    expect(screen.getByText('normalized')).toBeInTheDocument();
    expect(screen.getByText('fuzzy')).toBeInTheDocument();
    expect(screen.getByText('p1-b4')).toBeInTheDocument();
  });

  it('previews columns that are still being generated', () => {
    render(
      <ReviewTable
        table={table()}
        pendingColumns={['sample size', 'adverse events']}
        onCitationSelect={vi.fn()}
      />,
    );

    // The column already generated is not duplicated by its pending placeholder.
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent?.trim())).toEqual([
      'Paper',
      'sample size',
      'adverse events',
    ]);
  });
});
