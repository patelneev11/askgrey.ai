import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import { WorkspaceProvider } from '@/lib/workspace';
import { grounded, paperRow, table } from '@/test/fixtures';

import { LiteraturePage } from './LiteraturePage';

const extractFromUrl = vi.fn();
const extractFromUpload = vi.fn();
const exportTable = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      extractFromUrl: (...args: unknown[]) => extractFromUrl(...args),
      extractFromUpload: (...args: unknown[]) => extractFromUpload(...args),
      exportTable: (...args: unknown[]) => exportTable(...args),
    },
  };
});

function renderPage() {
  return render(
    <WorkspaceProvider>
      <LiteraturePage />
    </WorkspaceProvider>,
  );
}

const PAPER_URL = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf';

async function addUrlSource(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('PDF or PMC link'), PAPER_URL);
  await user.click(screen.getByRole('button', { name: 'Add link' }));
}

async function generate(user: ReturnType<typeof userEvent.setup>, goal = 'sample size') {
  await user.type(screen.getByLabelText('Extraction goal'), goal);
  await user.click(screen.getByRole('button', { name: 'Generate columns' }));
}

beforeEach(() => {
  window.localStorage.setItem('askgrey:access-token', 'token-123');
  extractFromUrl.mockResolvedValue(table());
  extractFromUpload.mockResolvedValue(table());
  exportTable.mockResolvedValue({
    blob: new Blob(['x'], { type: 'text/csv' }),
    filename: 'review-table.csv',
  });
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe('LiteraturePage — dynamic column generation', () => {
  it('turns an extraction goal into columns of extracted values', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText('No columns yet')).toBeInTheDocument();
    await addUrlSource(user);
    await generate(user);

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    expect(extractFromUrl).toHaveBeenCalledWith(PAPER_URL, 'sample size', 'token-123');
    expect(screen.getByRole('columnheader', { name: 'sample size' })).toBeInTheDocument();
    expect(screen.getByText('73 patients')).toBeInTheDocument();
  });

  it('extracts each added paper, uploads included, into one shared table', async () => {
    const user = userEvent.setup();
    extractFromUpload.mockResolvedValue(
      table({
        rows: [
          paperRow({
            document_id: 'doc-2',
            title: 'Uploaded trial',
            cells: { sample_size: grounded('210 patients') },
          }),
        ],
      }),
    );
    renderPage();

    await addUrlSource(user);
    await user.upload(
      screen.getByLabelText('Upload PDFs'),
      new File(['%PDF-1.4'], 'uploaded.pdf', { type: 'application/pdf' }),
    );
    await generate(user);

    await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(3));
    expect(extractFromUpload).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Uploaded trial')).toBeInTheDocument();
  });

  it('keeps an uploaded file as a source even though the input is reset straight away', async () => {
    const user = userEvent.setup();
    renderPage();

    const input = screen.getByLabelText('Upload PDFs');
    await user.upload(input, new File(['%PDF-1.4'], 'uploaded.pdf', { type: 'application/pdf' }));

    // The input is cleared so the same file can be picked twice; the source must survive it.
    expect((input as HTMLInputElement).value).toBe('');
    expect(screen.getByRole('listitem')).toHaveTextContent('uploaded.pdf');
  });

  it('needs both a paper and a goal before it will run', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('button', { name: 'Generate columns' })).toBeDisabled();
    await user.type(screen.getByLabelText('Extraction goal'), 'sample size');
    expect(screen.getByRole('button', { name: 'Generate columns' })).toBeDisabled();

    await addUrlSource(user);
    expect(screen.getByRole('button', { name: 'Generate columns' })).toBeEnabled();
  });

  it('says which prerequisite is missing rather than just greying the button out', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText('Add at least one paper to generate columns.')).toBeInTheDocument();
    await addUrlSource(user);
    expect(
      screen.getByText('Describe what to pull out of the papers to generate columns.'),
    ).toBeInTheDocument();
  });

  it('rejects a non-PDF upload at add time instead of queueing a doomed source', () => {
    renderPage();

    // Bypassing user.upload deliberately: it honours the input's accept filter, and the
    // point of the check is what happens when a browser hands us a non-PDF anyway.
    fireEvent.change(screen.getByLabelText('Upload PDFs'), {
      target: { files: [new File(['notes'], 'notes.txt', { type: 'text/plain' })] },
    });

    expect(screen.getByRole('alert')).toHaveTextContent('notes.txt is not a PDF');
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('rejects a link that is not an http(s) URL', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText('PDF or PMC link'), 'pmc123');
    await user.click(screen.getByRole('button', { name: 'Add link' }));

    expect(screen.getByRole('alert')).toHaveTextContent('is not a valid link');
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('shows the run as in flight, then reports how many values were cited', async () => {
    const user = userEvent.setup();
    let release: (value: unknown) => void = () => {};
    extractFromUrl.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    renderPage();

    await addUrlSource(user);
    await generate(user);

    expect(screen.getByText('extracting')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /sample size/ })).toBeInTheDocument();

    release(table());
    await waitFor(() => expect(screen.getByText('1 cited values')).toBeInTheDocument());
  });

  it('reports a failed paper without losing the rest of the run', async () => {
    const user = userEvent.setup();
    extractFromUrl.mockRejectedValue(new ApiError('PDF has no extractable text layer', 415));
    renderPage();

    await addUrlSource(user);
    await generate(user);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('PDF has no extractable text layer'),
    );
  });
});

describe('LiteraturePage — citation click-through', () => {
  it('opens the cited passage in the right pane and marks the cell', async () => {
    const user = userEvent.setup();
    renderPage();

    await addUrlSource(user);
    await generate(user);
    await waitFor(() => expect(screen.getByText('73 patients')).toBeInTheDocument());

    expect(screen.getByText('No passage selected')).toBeInTheDocument();
    const cell = screen.getByRole('button', { name: /show source for/i });
    await user.click(cell);

    expect(screen.getByText('page 4')).toBeInTheDocument();
    expect(
      screen.getByText('73 patients were randomized to ziprasidone or placebo'),
    ).toBeInTheDocument();
    expect(cell).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('LiteraturePage — export', () => {
  it('is unavailable until there is a table to export', async () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'Export .xlsx' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Export .csv' })).toBeDisabled();
  });

  it('downloads the rendered file the export endpoint returns', async () => {
    const user = userEvent.setup();
    renderPage();
    await addUrlSource(user);
    await generate(user);
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());

    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await user.click(screen.getByRole('button', { name: 'Export .xlsx' }));

    await waitFor(() => expect(exportTable).toHaveBeenCalledTimes(1));
    const [exported, format, , token] = exportTable.mock.calls[0];
    expect(exported.rows).toHaveLength(1);
    expect(format).toBe('xlsx');
    expect(token).toBe('token-123');
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it('surfaces an export failure instead of downloading an empty file', async () => {
    const user = userEvent.setup();
    exportTable.mockRejectedValue(new ApiError('table has no columns', 422));
    renderPage();
    await addUrlSource(user);
    await generate(user);
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Export .csv' }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('table has no columns'),
    );
  });

  it('lists each added paper as a removable source', async () => {
    const user = userEvent.setup();
    renderPage();
    await addUrlSource(user);

    const chip = screen.getByRole('listitem');
    expect(within(chip).getByText(PAPER_URL)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: `Remove ${PAPER_URL}` }));
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });
});
