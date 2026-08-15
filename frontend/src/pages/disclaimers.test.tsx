import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { OnboardingProvider } from '@/lib/onboarding';

import { AuditPage } from './AuditPage';
import { ProtocolPage } from './ProtocolPage';
import { RegulatoryPage } from './RegulatoryPage';
import { ScreeningPage } from './ScreeningPage';
import { SettingsPage } from './SettingsPage';

// These caveats are a product requirement, not decoration: the numbers on these pages are
// model output, so a regression that drops the warning is a correctness bug.
describe('unvalidated / draft disclaimers', () => {
  it('warns on Screening that predictions are not assay results', () => {
    render(<ScreeningPage />);

    expect(screen.getByRole('note')).toHaveTextContent(
      /computational approximations \(RDKit\/LLM\), not validated assay results/i,
    );
    expect(screen.getByText('predicted')).toBeInTheDocument();
  });

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
