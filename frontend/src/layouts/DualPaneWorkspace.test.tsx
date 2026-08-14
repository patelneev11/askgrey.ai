import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { DualPaneWorkspace } from './DualPaneWorkspace';

function renderWorkspace(props: Partial<Parameters<typeof DualPaneWorkspace>[0]> = {}) {
  return render(<DualPaneWorkspace left={<p>chat</p>} right={<p>viewer</p>} {...props} />);
}

describe('DualPaneWorkspace', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders both panes and a resize separator', () => {
    renderWorkspace();
    expect(screen.getByText('chat')).toBeInTheDocument();
    expect(screen.getByText('viewer')).toBeInTheDocument();
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '42');
  });

  it('moves the divider with the arrow keys', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const separator = screen.getByRole('separator');

    separator.focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(separator).toHaveAttribute('aria-valuenow', '46');

    await user.keyboard('{ArrowLeft}');
    expect(separator).toHaveAttribute('aria-valuenow', '44');
  });

  it('clamps the divider so neither pane can be collapsed away', async () => {
    const user = userEvent.setup();
    renderWorkspace({ defaultRatio: 0.22 });
    const separator = screen.getByRole('separator');

    separator.focus();
    await user.keyboard('{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowLeft}');
    expect(separator).toHaveAttribute('aria-valuenow', '20');
  });

  it('persists and restores the divider position per storage key', async () => {
    const user = userEvent.setup();
    const { unmount } = renderWorkspace({ storageKey: 'literature' });

    screen.getByRole('separator').focus();
    await user.keyboard('{ArrowRight}');
    unmount();

    renderWorkspace({ storageKey: 'literature' });
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '44');
  });

  it('restores the default ratio on double click', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const separator = screen.getByRole('separator');

    separator.focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    await user.dblClick(separator);
    expect(separator).toHaveAttribute('aria-valuenow', '42');
  });
});
