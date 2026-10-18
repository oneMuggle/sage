import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MessageSquare } from 'lucide-react';
import { describe, expect, it, beforeEach } from 'vitest';

import { NavGroup } from '../NavGroup';

const STORAGE_PREFIX = 'sage:nav-group:';

beforeEach(() => {
  localStorage.clear();
});

function renderGroup(overrides: Partial<React.ComponentProps<typeof NavGroup>> = {}) {
  return render(
    <NavGroup groupKey="test-group" label="测试组" icon={MessageSquare} collapsible {...overrides}>
      <div data-testid="child-1">Item 1</div>
      <div data-testid="child-2">Item 2</div>
    </NavGroup>,
  );
}

describe('NavGroup', () => {
  it('renders children when collapsible and expanded (default)', () => {
    renderGroup();
    expect(screen.getByTestId('child-1')).toBeInTheDocument();
    expect(screen.getByTestId('child-2')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-nav-group-test-group')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-nav-group-toggle-test-group')).toBeInTheDocument();
  });

  it('toggle button collapses children on click', async () => {
    renderGroup();
    const toggle = screen.getByTestId('sidebar-nav-group-toggle-test-group');
    fireEvent.click(toggle);

    // AnimatePresence exit animation → use waitFor
    await waitFor(() => {
      expect(screen.queryByTestId('child-1')).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('child-2')).not.toBeInTheDocument();
    expect(localStorage.getItem(`${STORAGE_PREFIX}test-group`)).toBe('1');
  });

  it('persist collapsed state across re-renders via localStorage', async () => {
    const { unmount } = renderGroup();
    fireEvent.click(screen.getByTestId('sidebar-nav-group-toggle-test-group'));
    await waitFor(() => {
      expect(screen.queryByTestId('child-1')).not.toBeInTheDocument();
    });
    unmount();

    renderGroup();
    // Re-mounted with localStorage '1' → starts collapsed (no children)
    expect(screen.queryByTestId('child-1')).not.toBeInTheDocument();
  });

  it('re-expanding restores children and updates localStorage', async () => {
    renderGroup();
    const toggle = screen.getByTestId('sidebar-nav-group-toggle-test-group');

    fireEvent.click(toggle);
    await waitFor(() => {
      expect(screen.queryByTestId('child-1')).not.toBeInTheDocument();
    });

    fireEvent.click(toggle);
    await waitFor(() => {
      expect(screen.getByTestId('child-1')).toBeInTheDocument();
    });
    expect(localStorage.getItem(`${STORAGE_PREFIX}test-group`)).toBe('0');
  });

  it('non-collapsible group always shows children, no toggle button', () => {
    renderGroup({ collapsible: false });
    expect(screen.getByTestId('child-1')).toBeInTheDocument();
    expect(screen.getByTestId('child-2')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-nav-group-toggle-test-group')).not.toBeInTheDocument();
  });

  it('defaultCollapsed=true starts collapsed', async () => {
    renderGroup({ defaultCollapsed: true });
    // Children not rendered when starting collapsed
    await waitFor(() => {
      expect(screen.queryByTestId('child-1')).not.toBeInTheDocument();
    });
    // Toggle shows aria-expanded=false
    const toggle = screen.getByTestId('sidebar-nav-group-toggle-test-group');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('aria-expanded reflects collapsed state', () => {
    renderGroup();
    const toggle = screen.getByTestId('sidebar-nav-group-toggle-test-group');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });
});
