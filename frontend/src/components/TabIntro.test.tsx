import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { OnboardingProvider } from '@/lib/onboarding';
import { TAB_INTROS } from '@/lib/tab-intros';
import { ScreeningPage } from '@/pages/ScreeningPage';

import { TabIntroHost } from './TabIntro';

const STORAGE_KEY = 'askgrey:onboarding:v1';

function seed(state: { tour?: string; acknowledged?: string[] } = {}) {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      tour: state.tour ?? 'skipped',
      step: 0,
      acknowledged: state.acknowledged ?? [],
    }),
  );
}

/** Renders the notice as the shell does: on a route, past the first-run tour. */
function renderAt(path: string, page?: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <OnboardingProvider>
        {page}
        <TabIntroHost />
      </OnboardingProvider>
    </MemoryRouter>,
  );
}

describe('first-encounter tab notices', () => {
  beforeEach(() => {
    window.localStorage.clear();
    seed();
  });

  it('covers every destination in the shell', () => {
    expect(TAB_INTROS.map((intro) => intro.path)).toEqual([
      '/literature',
      '/screening',
      '/protocol',
      '/regulatory',
      '/grants',
      '/workspace',
      '/audit',
      '/settings',
    ]);
    for (const intro of TAB_INTROS) {
      // Every notice says what the tab does and what the user is looking at.
      expect(intro.body.length).toBeGreaterThan(0);
    }
  });

  it('puts the unvalidated-approximation caveat in front of a first Screening visit', async () => {
    const user = userEvent.setup();
    const { unmount } = renderAt('/screening');

    const notice = screen.getByRole('dialog');
    expect(notice).toHaveTextContent(/computational approximations \(RDKit\/LLM\)/i);
    expect(notice).toHaveTextContent(/not validated assay results/i);

    await user.click(screen.getByRole('button', { name: 'I understand' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Acknowledgement is per tab and remembered: a first encounter, not a recurring nag.
    unmount();
    renderAt('/screening');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('asks for qualified review before a first Protocol visit', () => {
    renderAt('/protocol');

    expect(screen.getByRole('dialog')).toHaveTextContent(
      /requires qualified researcher review before anyone runs it at the bench/i,
    );
  });

  it('asks for regulatory affairs review before a first Regulatory visit', () => {
    renderAt('/regulatory');

    expect(screen.getByRole('dialog')).toHaveTextContent(
      /Requires qualified regulatory affairs review before any regulatory use/i,
    );
  });

  it('explains what a tab does even where there is no caveat to accept', () => {
    renderAt('/audit');

    const notice = screen.getByRole('dialog');
    expect(notice).toHaveTextContent(/Agent runs, document reads and exports land here/i);
    expect(notice).toHaveTextContent(/sample data/i);
    expect(screen.getByRole('button', { name: 'Got it' })).toBeInTheDocument();
  });

  it('acknowledges tabs one at a time', async () => {
    const user = userEvent.setup();
    renderAt('/screening');
    await user.click(screen.getByRole('button', { name: 'I understand' }));

    const state = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as {
      acknowledged: string[];
    };
    expect(state.acknowledged).toEqual(['screening']);

    renderAt('/grants');
    expect(screen.getByRole('dialog')).toHaveTextContent(/open federal calls/i);
  });

  it('stays out of the way until the first-run tour is done', () => {
    seed({ tour: 'unseen' });
    renderAt('/screening');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('leaves the standing caveat band on the page after the notice is dismissed', async () => {
    const user = userEvent.setup();
    renderAt('/screening', <ScreeningPage />);

    await user.click(screen.getByRole('button', { name: 'I understand' }));

    expect(screen.getByRole('note')).toHaveTextContent(
      /computational approximations \(RDKit\/LLM\).*not validated assay results/i,
    );
  });
});
