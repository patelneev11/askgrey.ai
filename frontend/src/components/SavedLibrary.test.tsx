import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import type { SavedArtifactSummary } from '@/lib/library';
import { setAccessToken } from '@/lib/session';

import { SavedLibrary } from './SavedLibrary';

const listArtifacts = vi.fn();
const saveArtifact = vi.fn();
const loadArtifact = vi.fn();
const deleteArtifact = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      listArtifacts: (...args: unknown[]) => listArtifacts(...args),
      saveArtifact: (...args: unknown[]) => saveArtifact(...args),
      loadArtifact: (...args: unknown[]) => loadArtifact(...args),
      deleteArtifact: (...args: unknown[]) => deleteArtifact(...args),
    },
  };
});

interface Report {
  summary: string;
  caveat: string;
}

const REPORT: Report = { summary: 'two of three rules pass', caveat: 'Not a legal determination.' };

function summary(overrides: Partial<SavedArtifactSummary> = {}): SavedArtifactSummary {
  return {
    id: 'artifact-1',
    kind: 'grants_eligibility',
    title: 'SBIR eligibility — Grey Labs',
    subtitle: REPORT.summary,
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  setAccessToken('token-123');
  listArtifacts.mockReset();
  saveArtifact.mockReset();
  loadArtifact.mockReset();
  deleteArtifact.mockReset();
  listArtifacts.mockResolvedValue([]);
  saveArtifact.mockImplementation((request: unknown) => Promise.resolve(request));
  loadArtifact.mockResolvedValue({ ...summary(), payload: REPORT });
  deleteArtifact.mockResolvedValue(undefined);
});

describe('saved library', () => {
  it('saves nothing until the researcher asks for it', async () => {
    render(
      <SavedLibrary<Report>
        kind="grants_eligibility"
        current={{ title: 'SBIR eligibility', payload: REPORT }}
        onOpen={vi.fn()}
      />,
    );

    await waitFor(() => expect(listArtifacts).toHaveBeenCalledWith('grants_eligibility', 'token-123'));
    expect(saveArtifact).not.toHaveBeenCalled();
    expect(screen.getByText(/Nothing saved yet/)).toBeInTheDocument();
  });

  it('cannot save when the panel has no result', () => {
    render(<SavedLibrary<Report> kind="grants_eligibility" current={null} onOpen={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Save to library' })).toBeDisabled();
  });

  it('sends the result as it stands and then lists it', async () => {
    const user = userEvent.setup();
    render(
      <SavedLibrary<Report>
        kind="grants_eligibility"
        current={{ title: 'SBIR eligibility', subtitle: REPORT.summary, payload: REPORT }}
        onOpen={vi.fn()}
      />,
    );
    await waitFor(() => expect(listArtifacts).toHaveBeenCalledTimes(1));
    listArtifacts.mockResolvedValue([summary()]);

    await user.click(screen.getByRole('button', { name: 'Save to library' }));

    await waitFor(() => expect(saveArtifact).toHaveBeenCalledTimes(1));
    expect(saveArtifact.mock.calls[0][0]).toEqual({
      kind: 'grants_eligibility',
      title: 'SBIR eligibility',
      subtitle: REPORT.summary,
      payload: REPORT,
    });
    expect(await screen.findByText('SBIR eligibility — Grey Labs')).toBeInTheDocument();
  });

  it('hands a reopened payload back with its own caveat intact', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    listArtifacts.mockResolvedValue([summary()]);
    render(<SavedLibrary<Report> kind="grants_eligibility" current={null} onOpen={onOpen} />);

    await user.click(await screen.findByText('SBIR eligibility — Grey Labs'));

    await waitFor(() => expect(loadArtifact).toHaveBeenCalledWith('artifact-1', 'token-123'));
    expect(onOpen).toHaveBeenCalledWith(REPORT);
  });

  it('drops a saved item on request', async () => {
    const user = userEvent.setup();
    listArtifacts.mockResolvedValue([summary()]);
    render(<SavedLibrary<Report> kind="grants_eligibility" current={null} onOpen={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: 'Delete SBIR eligibility — Grey Labs' }));

    await waitFor(() => expect(deleteArtifact).toHaveBeenCalledWith('artifact-1', 'token-123'));
  });

  it('reports a refused save instead of implying the result was kept', async () => {
    const user = userEvent.setup();
    saveArtifact.mockRejectedValue(new ApiError('that result is too large to save', 422));
    render(
      <SavedLibrary<Report>
        kind="grants_eligibility"
        current={{ title: 'SBIR eligibility', payload: REPORT }}
        onOpen={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Save to library' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('that result is too large to save');
  });
});
