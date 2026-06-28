import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k, locale: 'en', setLocale: vi.fn() }),
}));

const mockUseTheme = {
  active: { presetId: 'light' as string },
  setPreset: vi.fn(),
  applyCustomCss: vi.fn(),
  reset: vi.fn(),
  isLoading: false,
};
vi.mock('../ThemeProvider', () => ({ useTheme: () => mockUseTheme }));

import { ThemeSelector } from '../ThemeSelector';

describe('ThemeSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTheme.active = { presetId: 'light' };
  });

  it('renders 5 preset options when opened', () => {
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    const options = within(screen.getByRole('listbox')).getAllByRole('option');
    expect(options).toHaveLength(5);
  });

  it('marks active preset as selected', () => {
    mockUseTheme.active = { presetId: 'ocean' };
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    const active = screen.getByRole('option', { selected: true });
    expect(active.textContent).toMatch(/ocean/i);
  });

  it('calls setPreset when option clicked', () => {
    render(<ThemeSelector />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.selector\.title/i }));
    fireEvent.click(screen.getByRole('option', { name: /forest/i }));
    expect(mockUseTheme.setPreset).toHaveBeenCalledWith('forest');
  });
});
