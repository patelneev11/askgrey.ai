/** The shell and the workspace on a phone: a drawer instead of a rail, one pane at a time. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { AuthProvider } from '@/lib/auth';
import { OnboardingProvider } from '@/lib/onboarding';
import { COMPACT_QUERY } from '@/lib/useMediaQuery';

import { AppShell } from './AppShell';
import { DualPaneWorkspace } from './DualPaneWorkspace';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      refresh: () => Promise.reject(new Error('no session')),
      me: vi.fn(),
      terms: vi.fn().mockResolvedValue({ version: '2026-09-08' }),
      ssoConfig: vi.fn().mockResolvedValue({
        enabled: false,
        issuer: '',
        authorize_url: null,
        google_enabled: false,
      }),
    },
  };
});

/** jsdom has no layout, so the breakpoint is answered by this stub instead of a window size. */
function setViewport(compact: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query === COMPACT_QUERY ? compact : false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const originalMatchMedia = window.matchMedia;

beforeEach(() => setViewport(true));
afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/literature']}>
      <AuthProvider>
        <OnboardingProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/literature" element={<p>Literature</p>} />
            </Route>
          </Routes>
        </OnboardingProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('hides the navigation behind a menu button on a phone, and opens it on tap', async () => {
  renderShell();
  const user = userEvent.setup();

  const menu = await screen.findByRole('button', { name: /open navigation/i });
  expect(menu).toHaveAttribute('aria-expanded', 'false');

  await user.click(menu);
  expect(menu).toHaveAttribute('aria-expanded', 'true');
  // The scrim is a button too, so a tap anywhere outside the drawer closes it.
  expect(screen.getAllByRole('button', { name: /close navigation/i }).length).toBeGreaterThan(1);
});

it('closes the drawer on Escape, so the page underneath is reachable again', async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole('button', { name: /open navigation/i }));
  await user.keyboard('{Escape}');

  expect(await screen.findByRole('button', { name: /open navigation/i })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
});

it('shows one pane at a time on a phone, switched by a tab', async () => {
  const user = userEvent.setup();
  render(
    <DualPaneWorkspace
      left={<p>Sources list</p>}
      right={<p>Extracted table</p>}
      leftLabel="Sources"
      rightLabel="Results"
    />,
  );

  expect(screen.getAllByRole('tab')).toHaveLength(2);
  // Both panes stay mounted so a half-typed query survives the switch; only one is readable.
  expect(screen.getByText('Sources list')).toBeVisible();
  expect(screen.getByText('Extracted table')).not.toBeVisible();

  await user.click(screen.getByRole('tab', { name: 'Results' }));
  expect(screen.getByText('Extracted table')).toBeVisible();
  expect(screen.getByText('Sources list')).not.toBeVisible();
});

it('keeps both panes side by side on a desktop, with no tabs', () => {
  setViewport(false);
  render(
    <DualPaneWorkspace
      left={<p>Sources list</p>}
      right={<p>Extracted table</p>}
      leftLabel="Sources"
      rightLabel="Results"
    />,
  );

  expect(screen.queryAllByRole('tab')).toHaveLength(0);
  expect(screen.getByText('Sources list')).toBeInTheDocument();
  expect(screen.getByText('Extracted table')).toBeInTheDocument();
});
