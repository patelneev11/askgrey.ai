import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LiteraturePage } from '@/pages/LiteraturePage';
import { table } from '@/test/fixtures';

import { setAccessToken } from './session';

import { WorkspaceProvider } from './workspace';

const extractFromUrl = vi.fn();
const extractFromStoredDocument = vi.fn();
const loadWorkspace = vi.fn();
const saveWorkspace = vi.fn();
const documentPdf = vi.fn();
const deleteDocument = vi.fn();
const capabilities = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      extractFromUrl: (...args: unknown[]) => extractFromUrl(...args),
      extractFromUpload: vi.fn(),
      extractFromStoredDocument: (...args: unknown[]) => extractFromStoredDocument(...args),
      loadWorkspace: (...args: unknown[]) => loadWorkspace(...args),
      saveWorkspace: (...args: unknown[]) => saveWorkspace(...args),
      documentPdf: (...args: unknown[]) => documentPdf(...args),
      deleteDocument: (...args: unknown[]) => deleteDocument(...args),
      capabilities: (...args: unknown[]) => capabilities(...args),
      exportTable: vi.fn(),
    },
  };
});

const PAPER_URL = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf';

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/literature']}>
      <WorkspaceProvider>
        <nav>
          <Link to="/literature">Literature</Link>
          <Link to="/screening">Screening</Link>
        </nav>
        <Routes>
          <Route path="/literature" element={<LiteraturePage />} />
          <Route path="/screening" element={<p>Screening queue</p>} />
        </Routes>
      </WorkspaceProvider>
    </MemoryRouter>,
  );
}

const EMPTY_SAVED = { goal: '', sources: [], table: null };

beforeEach(() => {
  setAccessToken('token-123');
  extractFromUrl.mockResolvedValue(table());
  deleteDocument.mockResolvedValue(new Response(null, { status: 204 }));
  extractFromStoredDocument.mockResolvedValue(table());
  loadWorkspace.mockResolvedValue(EMPTY_SAVED);
  saveWorkspace.mockResolvedValue(EMPTY_SAVED);
  documentPdf.mockRejectedValue(new Error('no stored copy'));
  capabilities.mockResolvedValue({ extraction_available: true });
});

afterEach(() => {
  vi.clearAllMocks();
  setAccessToken(undefined);
  window.localStorage.clear();
});

describe('WorkspaceProvider', () => {
  it('keeps the generated table when the user visits another tab and comes back', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.type(screen.getByLabelText('PDF or PMC link'), PAPER_URL);
    await user.click(screen.getByRole('button', { name: 'Add link' }));
    await user.type(screen.getByLabelText('Extraction goal'), 'sample size');
    await user.click(screen.getByRole('button', { name: 'Generate columns' }));
    await waitFor(() => expect(screen.getByText('73 patients')).toBeInTheDocument());

    await user.click(screen.getByRole('link', { name: 'Screening' }));
    expect(screen.getByText('Screening queue')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Literature' }));
    expect(screen.getByText('73 patients')).toBeInTheDocument();
    expect(screen.getByLabelText('Extraction goal')).toHaveValue('sample size');
    expect(screen.getByText(PAPER_URL)).toBeInTheDocument();
  });

  it('clears a failure once the user changes which papers are queued', async () => {
    const user = userEvent.setup();
    extractFromUrl.mockRejectedValueOnce(new Error('scanned PDF is unsupported'));
    renderApp();

    await user.type(screen.getByLabelText('PDF or PMC link'), PAPER_URL);
    await user.click(screen.getByRole('button', { name: 'Add link' }));
    await user.type(screen.getByLabelText('Extraction goal'), 'sample size');
    await user.click(screen.getByRole('button', { name: 'Generate columns' }));
    await waitFor(() => expect(screen.getByText(/scanned PDF is unsupported/)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: `Remove ${PAPER_URL}` }));
    expect(screen.queryByText(/scanned PDF is unsupported/)).not.toBeInTheDocument();
  });

  it('stops showing a paper’s findings once that paper is removed', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.type(screen.getByLabelText('PDF or PMC link'), PAPER_URL);
    await user.click(screen.getByRole('button', { name: 'Add link' }));
    await user.type(screen.getByLabelText('Extraction goal'), 'sample size');
    await user.click(screen.getByRole('button', { name: 'Generate columns' }));
    await waitFor(() => expect(screen.getByText('73 patients')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: `Remove ${PAPER_URL}` }));

    expect(screen.queryByText('73 patients')).not.toBeInTheDocument();
    // Removing it has to delete the stored bytes as well, not wait out the retention window.
    expect(deleteDocument).toHaveBeenCalledWith(expect.any(String), 'token-123');
  });

  it('restores the saved workspace so a reload does not lose the review', async () => {
    loadWorkspace.mockResolvedValue({
      goal: 'sample size',
      sources: [
        {
          id: 'paper.pdf:1',
          label: 'paper.pdf',
          kind: 'upload',
          url: '',
          document_id: 'doc-1',
        },
      ],
      table: table(),
    });

    renderApp();

    await waitFor(() => expect(screen.getByText('73 patients')).toBeInTheDocument());
    expect(screen.getByLabelText('Extraction goal')).toHaveValue('sample size');
    expect(screen.getByText('paper.pdf')).toBeInTheDocument();
  });

  it('saves the workspace after the user stops editing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();

    await user.type(screen.getByLabelText('PDF or PMC link'), PAPER_URL);
    await user.click(screen.getByRole('button', { name: 'Add link' }));
    await vi.advanceTimersByTimeAsync(1000);

    await waitFor(() =>
      expect(saveWorkspace).toHaveBeenCalledWith(
        expect.objectContaining({
          sources: [expect.objectContaining({ kind: 'url', url: PAPER_URL })],
        }),
        'token-123',
      ),
    );
    vi.useRealTimers();
  });

  it('re-extracts a restored upload from the copy the server kept', async () => {
    loadWorkspace.mockResolvedValue({
      goal: '',
      sources: [
        { id: 'paper.pdf:1', label: 'paper.pdf', kind: 'upload', url: '', document_id: 'doc-1' },
      ],
      table: null,
    });
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('paper.pdf');

    await user.type(screen.getByLabelText('Extraction goal'), 'sample size');
    await user.click(screen.getByRole('button', { name: 'Generate columns' }));

    await waitFor(() =>
      expect(extractFromStoredDocument).toHaveBeenCalledWith('doc-1', 'sample size', 'token-123'),
    );
    expect(screen.getByText('73 patients')).toBeInTheDocument();
  });
});
