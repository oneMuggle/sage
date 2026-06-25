// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '../ThemeProvider';
import { useTheme } from '../useTheme';

// Mock themeCssClient
vi.mock('../../../shared/api/themeCssClient', () => ({
  themeCssClient: {
    list: vi.fn(),
  },
}));

// Mock backgroundInjector
vi.mock('../../../features/theme/backgroundInjector', () => ({
  injectPersistedStyle: vi.fn(),
}));

// Mock storage
vi.mock('../../../entities/theme/storage', () => ({
  loadTheme: vi.fn().mockResolvedValue(null),
  saveTheme: vi.fn().mockResolvedValue(undefined),
  loadThemePreset: vi.fn().mockResolvedValue(null),
  saveThemePreset: vi.fn().mockResolvedValue(undefined),
}));

import { themeCssClient } from '../../../shared/api/themeCssClient';
import { injectPersistedStyle } from '../../../features/theme/backgroundInjector';

const mockedThemeCssClient = vi.mocked(themeCssClient);
const mockedInjectPersistedStyle = vi.mocked(injectPersistedStyle);

function TestConsumer() {
  const { cssThemes, activeSource, setActiveCssTheme, refreshCssThemes } = useTheme();
  return (
    <div>
      <div data-testid="css-themes-count">{cssThemes.length}</div>
      <div data-testid="active-source-kind">{activeSource.kind}</div>
      <div data-testid="active-source-id">
        {activeSource.kind === 'css' ? activeSource.id : 'none'}
      </div>
      <button data-testid="switch-css-theme" onClick={() => setActiveCssTheme('test-theme-1')}>
        Switch
      </button>
      <button data-testid="refresh" onClick={() => void refreshCssThemes()}>
        Refresh
      </button>
    </div>
  );
}

describe('ThemeProvider CSS theme integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('loads CSS themes on mount', async () => {
    const mockThemes = [
      {
        id: 'test-theme-1',
        name: 'Test Theme 1',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
      {
        id: 'test-theme-2',
        name: 'Test Theme 2',
        css: ':root { --bg-base: #000; }',
        appearance: 'dark' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];
    mockedThemeCssClient.list.mockResolvedValue(mockThemes);

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('css-themes-count').textContent).toBe('2');
    });

    // 验证每个主题都调用了 injectPersistedStyle
    expect(mockedInjectPersistedStyle).toHaveBeenCalledTimes(2);
    expect(mockedInjectPersistedStyle).toHaveBeenCalledWith(
      'test-theme-1',
      ':root { --bg-base: #fff; }',
    );
    expect(mockedInjectPersistedStyle).toHaveBeenCalledWith(
      'test-theme-2',
      ':root { --bg-base: #000; }',
    );
  });

  it('defaults to preset theme when no CSS theme saved', async () => {
    mockedThemeCssClient.list.mockResolvedValue([]);

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('active-source-kind').textContent).toBe('preset');
    });
  });

  it('restores active CSS theme from localStorage', async () => {
    const mockThemes = [
      {
        id: 'test-theme-1',
        name: 'Test Theme 1',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];
    mockedThemeCssClient.list.mockResolvedValue(mockThemes);
    localStorage.setItem('sage-active-css-theme', 'test-theme-1');

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('active-source-kind').textContent).toBe('css');
      expect(screen.getByTestId('active-source-id').textContent).toBe('test-theme-1');
    });
  });

  it('setActiveCssTheme updates active source and saves to localStorage', async () => {
    const mockThemes = [
      {
        id: 'test-theme-1',
        name: 'Test Theme 1',
        css: ':root { --bg-base: #fff; }',
        appearance: 'light' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];
    mockedThemeCssClient.list.mockResolvedValue(mockThemes);

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('css-themes-count').textContent).toBe('1');
    });

    screen.getByTestId('switch-css-theme').click();

    await waitFor(() => {
      expect(screen.getByTestId('active-source-kind').textContent).toBe('css');
      expect(screen.getByTestId('active-source-id').textContent).toBe('test-theme-1');
      expect(localStorage.getItem('sage-active-css-theme')).toBe('test-theme-1');
    });
  });

  it('refreshCssThemes reloads themes from client', async () => {
    mockedThemeCssClient.list.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('css-themes-count').textContent).toBe('0');
    });

    const newThemes = [
      {
        id: 'new-theme',
        name: 'New Theme',
        css: ':root { --bg-base: #123; }',
        appearance: 'dark' as const,
        created_at: 1700000000000,
        updated_at: 1700000000000,
      },
    ];
    mockedThemeCssClient.list.mockResolvedValue(newThemes);

    screen.getByTestId('refresh').click();

    await waitFor(() => {
      expect(screen.getByTestId('css-themes-count').textContent).toBe('1');
    });
  });

  it('handles themeCssClient.list failure gracefully', async () => {
    mockedThemeCssClient.list.mockRejectedValue(new Error('IPC failed'));

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    // 应该优雅降级，不崩溃
    await waitFor(() => {
      expect(screen.getByTestId('css-themes-count').textContent).toBe('0');
    });
  });
});
