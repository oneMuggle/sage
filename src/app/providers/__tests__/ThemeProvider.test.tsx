import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '../ThemeProvider';
import { useTheme } from '../useTheme';

const { mockLoad, mockSave, mockLoadPreset, mockSavePreset } = vi.hoisted(() => ({
  mockLoad: vi.fn(),
  mockSave: vi.fn(),
  mockLoadPreset: vi.fn(),
  mockSavePreset: vi.fn(),
}));

vi.mock('../../../entities/theme/storage', () => ({
  loadTheme: (...args: unknown[]) => mockLoad(...args),
  saveTheme: (...args: unknown[]) => mockSave(...args),
  loadThemePreset: (...args: unknown[]) => mockLoadPreset(...args),
  saveThemePreset: (...args: unknown[]) => mockSavePreset(...args),
}));

describe('ThemeProvider async init', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    mockLoad.mockReset();
    mockSave.mockReset();
    mockLoadPreset.mockReset();
    mockSavePreset.mockReset();
    mockLoadPreset.mockResolvedValue(null);
    mockSavePreset.mockResolvedValue(undefined);
  });

  it('useEffect 触发 loadTheme 并 apply 到 <html>', async () => {
    mockLoad.mockResolvedValue('dark');
    render(
      <ThemeProvider>
        <div>child</div>
      </ThemeProvider>,
    );
    expect(screen.getByText('child')).toBeInTheDocument();
    await waitFor(() => {
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });

  it('loadTheme 失败时回退 defaultMode=system', async () => {
    mockLoad.mockResolvedValue(null);
    render(
      <ThemeProvider>
        <div>child</div>
      </ThemeProvider>,
    );
    await waitFor(() => expect(mockLoad).toHaveBeenCalled());
    // system 模式 → resolved=light (假设测试环境 matchMedia=false)
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('保存主题时调 saveTheme', async () => {
    mockLoad.mockResolvedValue('light');
    mockSave.mockResolvedValue(undefined);
    const TestConsumer = () => {
      const { setMode } = useTheme();
      return <button onClick={() => setMode('dark')}>change</button>;
    };
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );
    await waitFor(() => expect(mockLoad).toHaveBeenCalled());
    screen.getByText('change').click();
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith('dark'));
  });
});
