import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { Sidebar } from './Sidebar';
import { OPERATIONAL_TABS, WORKSPACE_LINKS } from './navigation';

function renderSidebar(collapsed = false, onToggle = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/literature']}>
      <Sidebar collapsed={collapsed} onToggle={onToggle} />
    </MemoryRouter>,
  );
  return onToggle;
}

describe('Sidebar', () => {
  it('links to every operational tab and workspace destination', () => {
    renderSidebar();
    for (const item of [...OPERATIONAL_TABS, ...WORKSPACE_LINKS]) {
      expect(screen.getByRole('link', { name: item.label })).toHaveAttribute('href', item.to);
    }
  });

  it('marks the current route as active', () => {
    renderSidebar();
    expect(screen.getByRole('link', { name: 'Literature' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('reports its expanded state and fires the toggle handler', async () => {
    const user = userEvent.setup();
    const onToggle = renderSidebar(false);
    const toggle = screen.getByRole('button', { name: 'Collapse sidebar' });

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await user.click(toggle);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it('exposes labels as tooltips when collapsed', () => {
    renderSidebar(true);
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Screening' })).toHaveAttribute('title', 'Screening');
  });
});
