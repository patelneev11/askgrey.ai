import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { OnboardingProvider } from '@/lib/onboarding';
import { SettingsPage } from '@/pages/SettingsPage';

import { FirstRunTour } from './FirstRunTour';

const STORAGE_KEY = 'askgrey:onboarding:v1';

function renderTour() {
  return render(
    <OnboardingProvider>
      <FirstRunTour />
    </OnboardingProvider>,
  );
}

function stored() {
  return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Record<string, unknown>;
}

describe('first-run tour', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('opens for a user who has never seen it and walks forward and back', async () => {
    const user = userEvent.setup();
    renderTour();

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('1 of 4');
    expect(dialog).toHaveTextContent(/research workspace with its sources attached/i);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('2 of 4');

    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('1 of 4');
    // Back on the first screen there is nowhere further back to go.
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });

  it('states plainly what each group of tabs runs on, and what is missing', async () => {
    const user = userEvent.setup();
    renderTour();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(
      /Literature, Screening, Protocol, Regulatory and Grants all run against real services/i,
    );
    expect(dialog).toHaveTextContent(/Workspace, Audit and Settings report your account/i);
    // The absent org features are named here, because the pages no longer draw them at all.
    expect(dialog).toHaveTextContent(
      /shared workspaces, seats and third-party integrations are not built/i,
    );
  });

  it('skips: closes immediately and stays closed on the next visit', async () => {
    const user = userEvent.setup();
    const { unmount } = renderTour();

    await user.click(screen.getByRole('button', { name: 'Skip' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(stored().tour).toBe('skipped');

    unmount();
    renderTour();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('completes only from the last step, and does not reopen afterwards', async () => {
    const user = userEvent.setup();
    const { unmount } = renderTour();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));

    expect(screen.getByRole('dialog')).toHaveTextContent('4 of 4');
    await user.click(screen.getByRole('button', { name: 'Start working' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(stored().tour).toBe('completed');

    unmount();
    renderTour();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('resumes on the step the user left rather than restarting', async () => {
    const user = userEvent.setup();
    const { unmount } = renderTour();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('3 of 4');

    // Standing in for closing the tab mid-tour: state comes back from storage, not memory.
    unmount();
    renderTour();

    expect(screen.getByRole('dialog')).toHaveTextContent('3 of 4');
  });

  it('resumes safely when stored state points past the last step', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ tour: 'unseen', step: 99, acknowledged: [] }),
    );
    renderTour();

    expect(screen.getByRole('dialog')).toHaveTextContent('4 of 4');
  });

  it('starts from the beginning when stored state is unreadable', () => {
    window.localStorage.setItem(STORAGE_KEY, 'not json');
    renderTour();

    expect(screen.getByRole('dialog')).toHaveTextContent('1 of 4');
  });

  it('can be replayed from Settings after it has been completed', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ tour: 'completed', step: 0, acknowledged: [] }),
    );
    render(
      <OnboardingProvider>
        <FirstRunTour />
        <SettingsPage />
      </OnboardingProvider>,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Replay tour' }));

    expect(screen.getByRole('dialog')).toHaveTextContent('1 of 4');
  });

  it('leaves a resumable tour alone when the user only wants to look around', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ tour: 'skipped', step: 2, acknowledged: [] }),
    );
    renderTour();

    // Skipped mid-way stays skipped: the remembered step only matters if the tour is replayed.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
