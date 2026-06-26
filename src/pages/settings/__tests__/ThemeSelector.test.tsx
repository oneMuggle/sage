// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeSelector } from '../ThemeSelector';

// Mock useTheme
const mockUseTheme = vi.fn();

vi.mock('../../../app/providers/useTheme', () => ({
  useTheme: () => mockUseTheme(),
}));

// Mock themeCssClient
const mockDelete = vi.fn();
vi.mock('../../../shared/api/themeCssClient', () => ({
  themeCssClient: {
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}));

// Mock CssThemeModal
vi.mock('../../../features/theme/CssThemeModal', () => ({
  CssThemeModal: ({ open, onClose }: { open: boolean; onClose: () => void }) => {
    if (!open) return null;
    return (
      <div data-testid="css-theme-modal">
        <button onClick={onClose}>Close Modal</button>
      </div>
    );
  },
}));

// Mock ThemeGallery
vi.mock('../../../features/theme/ThemeGallery', () => ({
  ThemeGallery: () => <div data-testid="theme-gallery">ThemeGallery</div>,
}));

// Mock useI18n
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'settings.section.theme': '主题',
        'theme.gallery.section_basic': '基础主题',
        'theme.gallery.section_decorative': '装饰主题',
      };
      return translations[key] ?? key;
    },
  }),
}));

// Mock confirm
window.confirm = vi.fn(() => true);

describe('ThemeSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default mock return value
    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: [],
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
      refreshCssThemes: vi.fn().mockResolvedValue(undefined),
    });
  });

  it('renders ThemeGallery for preset themes', () => {
    render(<ThemeSelector />);

    expect(screen.getByTestId('theme-gallery')).toBeInTheDocument();
    expect(screen.getByText('主题')).toBeInTheDocument();
  });

  it('renders "New Custom" button', () => {
    render(<ThemeSelector />);

    expect(screen.getByText('新建自定义')).toBeInTheDocument();
  });

  it('opens modal when "New Custom" button clicked', () => {
    render(<ThemeSelector />);

    fireEvent.click(screen.getByText('新建自定义'));

    expect(screen.getByTestId('css-theme-modal')).toBeInTheDocument();
  });

  it('shows empty state when no CSS themes', () => {
    render(<ThemeSelector />);

    expect(screen.getByText('尚未创建自定义主题')).toBeInTheDocument();
  });

  it('renders CSS themes when present', () => {
    const mockCssThemes = [
      {
        id: 'theme-1',
        name: 'My Custom Theme',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];

    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: mockCssThemes,
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
      refreshCssThemes: vi.fn().mockResolvedValue(undefined),
    });

    render(<ThemeSelector />);

    expect(screen.getByText('My Custom Theme')).toBeInTheDocument();
  });

  it('calls setActiveCssTheme when clicking a CSS theme', () => {
    const mockSetActiveCssTheme = vi.fn();
    const mockCssThemes = [
      {
        id: 'theme-1',
        name: 'My Custom Theme',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];

    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: mockCssThemes,
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: mockSetActiveCssTheme,
      refreshCssThemes: vi.fn().mockResolvedValue(undefined),
    });

    render(<ThemeSelector />);

    // The cover placeholder button triggers setActiveCssTheme
    const coverButton = screen.getByText('浅色').closest('button');
    fireEvent.click(coverButton!);

    expect(mockSetActiveCssTheme).toHaveBeenCalledWith('theme-1');
  });

  it('calls delete and refresh when delete button clicked', async () => {
    const mockRefreshCssThemes = vi.fn().mockResolvedValue(undefined);
    const mockCssThemes = [
      {
        id: 'theme-1',
        name: 'My Custom Theme',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];

    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: mockCssThemes,
      activeSource: { kind: 'preset', id: 'indigo' },
      setActiveCssTheme: vi.fn(),
      refreshCssThemes: mockRefreshCssThemes,
    });

    mockDelete.mockResolvedValue(undefined);

    render(<ThemeSelector />);

    // Find the delete button (Trash2 icon button)
    const deleteButton = screen.getByTitle('删除主题');
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('theme-1');
      expect(mockRefreshCssThemes).toHaveBeenCalled();
    });
  });

  it('highlights active CSS theme', () => {
    const mockCssThemes = [
      {
        id: 'theme-1',
        name: 'My Custom Theme',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];

    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
      cssThemes: mockCssThemes,
      activeSource: { kind: 'css', id: 'theme-1' },
      setActiveCssTheme: vi.fn(),
      refreshCssThemes: vi.fn().mockResolvedValue(undefined),
    });

    render(<ThemeSelector />);

    const themeName = screen.getByText('My Custom Theme');
    expect(themeName).toHaveClass('text-primary');
  });

  it('ThemeGallery handles preset switching (delegated)', () => {
    // Preset switching is now handled by ThemeGallery component
    // which has its own tests for this behavior
    render(<ThemeSelector />);
    expect(screen.getByTestId('theme-gallery')).toBeInTheDocument();
  });
});
