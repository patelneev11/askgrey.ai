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

  it('shows the page number, flagging only a genuinely approximate match', () => {
    const { rerender } = render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);
    expect(screen.getByText('p4')).toBeInTheDocument();

    // A normalized match only folded whitespace before matching: still verified.
    rerender(
      <ReviewTable
        table={table({
          rows: [paperRow({ cells: { sample_size: grounded('73 patients', 'normalized') } })],
        })}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('p4')).toBeInTheDocument();

    rerender(
      <ReviewTable
        table={table({
          rows: [paperRow({ cells: { sample_size: grounded('73 patients', 'fuzzy') } })],
        })}
        onCitationSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('p4 close')).toBeInTheDocument();
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

    await userEvent.click(screen.getByText('2 warnings'));
    expect(screen.getByText('page 3 is a scanned image')).toBeInTheDocument();
    expect(screen.getByText('no abstract detected')).toBeInTheDocument();
  });

  it('explains the result vocabulary in a legend', () => {
    render(<ReviewTable table={table()} onCitationSelect={vi.fn()} />);

    expect(screen.getByText(/quote located on page 1/i)).toBeInTheDocument();
    expect(screen.getByText(/could not be traced to a passage/i)).toBeInTheDocument();
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
