import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LiteraturePage } from '@/pages/LiteraturePage';
import { table } from '@/test/fixtures';

import { WorkspaceProvider } from './workspace';

const extractFromUrl = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      extractFromUrl: (...args: unknown[]) => extractFromUrl(...args),
      extractFromUpload: vi.fn(),
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

beforeEach(() => {
  window.localStorage.setItem('askgrey:access-token', 'token-123');
  extractFromUrl.mockResolvedValue(table());
});

afterEach(() => {
  vi.clearAllMocks();
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
});
