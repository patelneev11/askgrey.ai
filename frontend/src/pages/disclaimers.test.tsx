import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { OnboardingProvider } from '@/lib/onboarding';

import { AuditPage } from './AuditPage';
import { ProtocolPage } from './ProtocolPage';
import { RegulatoryPage } from './RegulatoryPage';
import { SettingsPage } from './SettingsPage';
import { WorkspacePage } from './WorkspacePage';

// These caveats are a product requirement, not decoration: the numbers on these pages are
// model output, so a regression that drops the warning is a correctness bug.
// Screening renders its caveats over a live payload, so they are asserted against the rendered
// results in ScreeningPage.test.tsx rather than here.
describe('unvalidated / draft disclaimers', () => {
  it('warns on Protocol and Regulatory that drafts need qualified review', () => {
    const { unmount } = render(<ProtocolPage />);
    expect(screen.getByRole('note')).toHaveTextContent(
      /Agent-drafted content\. Requires qualified researcher review/i,
    );
    unmount();

    render(<RegulatoryPage />);
    expect(screen.getByRole('note')).toHaveTextContent(
      /Agent-drafted content\. Requires qualified researcher review/i,
    );
  });
});

describe('sample surfaces', () => {
  // The one-time onboarding notice says this page is invented; the page has to keep saying so
  // once that notice is gone, or named members and "Connected" integrations read as fact.
  it('marks Workspace as sample data rather than claiming a compliance posture', () => {
    render(<WorkspacePage />);

    expect(screen.getByText('Sample data · read-only')).toBeInTheDocument();
    expect(screen.queryByText('SOC 2 controls active')).not.toBeInTheDocument();
  });

  it('labels Settings as read-only sample data and disables its controls', () => {
    render(
      <OnboardingProvider>
        <SettingsPage />
      </OnboardingProvider>,
    );

    expect(screen.getByText('Sample data · read-only')).toBeInTheDocument();
    for (const toggle of screen.getAllByRole('switch')) {
      expect(toggle).toBeDisabled();
    }
  });

  it('actually filters the audit timeline instead of only looking active', async () => {
    render(<AuditPage />);

    expect(screen.getByText('Sample data')).toBeInTheDocument();
    const before = screen.getAllByRole('listitem').length;

    await userEvent.click(screen.getByRole('button', { name: 'Exports' }));

    const after = screen.getAllByRole('listitem');
    expect(after.length).toBeLessThan(before);
    expect(after[0]).toHaveTextContent('Exported protocol to Benchling');
  });
});
