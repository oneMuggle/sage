// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { FEATURE_UNLOCK_STORAGE_KEY } from '../../../shared/lib/hooks/useFeatureUnlock';
import { ArenaAccountsToggle } from '../ArenaAccountsToggle';

beforeEach(() => {
  localStorage.clear();
});

describe('ArenaAccountsToggle', () => {
  it('renders off by default and shows the description', () => {
    render(<ArenaAccountsToggle />);
    expect(screen.getByText('Arena 自动化')).toBeInTheDocument();
    expect(screen.getByText(/侧边栏显示「Arena 账号」入口/)).toBeInTheDocument();
    expect(screen.getByTestId('toggle-arena-accounts')).toHaveClass('bg-border');
  });

  it('hydrates the on state from localStorage', () => {
    localStorage.setItem(
      FEATURE_UNLOCK_STORAGE_KEY,
      JSON.stringify(['arena-accounts']),
    );
    render(<ArenaAccountsToggle />);
    expect(screen.getByTestId('toggle-arena-accounts')).toHaveClass('bg-primary');
  });

  it('clicking the toggle persists arena-accounts to localStorage', () => {
    render(<ArenaAccountsToggle />);
    const toggle = screen.getByTestId('toggle-arena-accounts');
    fireEvent.click(toggle);
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('arena-accounts');
    expect(toggle).toHaveClass('bg-primary');
  });

  it('clicking twice (on then off) removes the key from localStorage', () => {
    render(<ArenaAccountsToggle />);
    const toggle = screen.getByTestId('toggle-arena-accounts');
    fireEvent.click(toggle); // off → on
    fireEvent.click(toggle); // on → off
    const raw = localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY);
    const stored = raw == null ? [] : JSON.parse(raw);
    expect(stored).not.toContain('arena-accounts');
    expect(toggle).toHaveClass('bg-border');
  });
});
