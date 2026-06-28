import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k, locale: 'en', setLocale: vi.fn() }),
}));

const mockUseTheme = {
  active: { presetId: 'ocean' as string },
  setPreset: vi.fn(),
  applyCustomCss: vi.fn(),
  reset: vi.fn(),
  isLoading: false,
};
vi.mock('../ThemeProvider', () => ({ useTheme: () => mockUseTheme }));
vi.mock('../CodeMirrorThemeEditor', () => ({
  CodeMirrorThemeEditor: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (v: string) => void;
  }) => (
    <textarea
      data-testid="cm-mock"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));
vi.mock('../../../shared/lib/theme/cssValidator', () => ({
  validateCss: vi.fn((css: string) => {
    if (css.includes('@import')) return { valid: false, errors: ['CSS_INJECTION_FORBIDDEN'] };
    return { valid: true };
  }),
}));

import { CssThemeModal } from '../CssThemeModal';

describe('CssThemeModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTheme.active = { presetId: 'ocean' };
  });

  it('renders editor when open', () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    expect(screen.getByTestId('cm-mock')).toBeTruthy();
  });

  it('Save calls applyCustomCss with current CSS', async () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    fireEvent.change(screen.getByTestId('cm-mock'), {
      target: { value: ':root { --color-bg: #f00; }' },
    });
    fireEvent.click(screen.getByRole('button', { name: /theme\.editor\.save/i }));
    await waitFor(() => {
      expect(mockUseTheme.applyCustomCss).toHaveBeenCalledWith(':root { --color-bg: #f00; }');
    });
  });

  it('disables Save and shows error on invalid CSS', () => {
    render(<CssThemeModal open onClose={vi.fn()} />);
    fireEvent.change(screen.getByTestId('cm-mock'), {
      target: { value: '@import url("evil.css")' },
    });
    expect(screen.getByRole('button', { name: /theme\.editor\.save/i })).toBeDisabled();
    expect(screen.getByText(/CSS_INJECTION_FORBIDDEN/i)).toBeTruthy();
  });

  it('Cancel calls onClose without saving', () => {
    const onClose = vi.fn();
    render(<CssThemeModal open onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /theme\.editor\.cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('does not render when open=false', () => {
    render(<CssThemeModal open={false} onClose={vi.fn()} />);
    expect(screen.queryByTestId('cm-mock')).toBeNull();
  });
});