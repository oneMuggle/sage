import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { Sidebar } from '../Sidebar';

function renderSidebar(opts: { collapsed?: boolean; onToggleCollapse?: () => void } = {}) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar collapsed={opts.collapsed} onToggleCollapse={opts.onToggleCollapse} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('Sidebar — collapse/expand toggle button', () => {
  it('renders collapse button when expanded and onToggleCollapse provided', () => {
    const onClick = vi.fn();
    renderSidebar({ collapsed: false, onToggleCollapse: onClick });

    const btn = screen.getByTestId('sidebar-collapse-button');
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute('aria-label')).toBe('折叠侧边栏');

    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders expand button when collapsed and onToggleCollapse provided', () => {
    const onClick = vi.fn();
    renderSidebar({ collapsed: true, onToggleCollapse: onClick });

    const btn = screen.getByTestId('sidebar-expand-button');
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute('aria-label')).toBe('展开侧边栏');

    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('does NOT render toggle buttons when onToggleCollapse is omitted', () => {
    const { container } = renderSidebar({ collapsed: false });
    expect(container.querySelector('[data-testid="sidebar-collapse-button"]')).toBeNull();
  });

  it('does NOT render toggle buttons in collapsed rail when onToggleCollapse omitted', () => {
    const { container } = renderSidebar({ collapsed: true });
    expect(container.querySelector('[data-testid="sidebar-expand-button"]')).toBeNull();
  });
});
