// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { zh } from '../../../shared/lib/i18n/zh';
import { ThemeModeSelect } from '../ThemeModeSelect';

const mockUseTheme = vi.fn();

vi.mock('../../../app/providers/useTheme', () => ({
  useTheme: () => mockUseTheme(),
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => (zh as Record<string, string>)[key] ?? key,
  }),
}));

describe('ThemeModeSelect', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the three theme modes with the current one checked', () => {
    mockUseTheme.mockReturnValue({ mode: 'dark', resolved: 'dark', setMode: vi.fn() });
    render(<ThemeModeSelect />);

    expect(screen.getByRole('radiogroup', { name: '主题模式' })).toBeInTheDocument();
    expect(screen.getByTestId('theme-mode-light')).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByTestId('theme-mode-dark')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('theme-mode-system')).toHaveAttribute('aria-checked', 'false');
  });

  it('switches to each mode on click', () => {
    const setMode = vi.fn();
    mockUseTheme.mockReturnValue({ mode: 'system', resolved: 'light', setMode });
    render(<ThemeModeSelect />);

    fireEvent.click(screen.getByTestId('theme-mode-light'));
    fireEvent.click(screen.getByTestId('theme-mode-dark'));
    fireEvent.click(screen.getByTestId('theme-mode-system'));

    expect(setMode.mock.calls).toEqual([['light'], ['dark'], ['system']]);
  });

  it('shows the resolved system appearance when following the system', () => {
    mockUseTheme.mockReturnValue({ mode: 'system', resolved: 'dark', setMode: vi.fn() });
    render(<ThemeModeSelect />);

    expect(screen.getByText('跟随系统设置（当前系统为深色）')).toBeInTheDocument();
  });

  it('shows the static hint for explicit light/dark modes', () => {
    mockUseTheme.mockReturnValue({ mode: 'light', resolved: 'light', setMode: vi.fn() });
    render(<ThemeModeSelect />);

    expect(screen.getByText('选择浅色或深色外观，也可以跟随系统设置')).toBeInTheDocument();
  });
});
