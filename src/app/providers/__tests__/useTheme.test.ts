import { renderHook } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import {
  formatThemeAuditJson,
  formatThemeAuditSummary,
  ThemeContext,
  useTheme,
} from '../useTheme';

describe('useTheme', () => {
  it('throws when called outside ThemeProvider', () => {
    expect(() => renderHook(() => useTheme())).toThrow(
      'useTheme must be used within a <ThemeProvider>',
    );
  });

  it('returns theme context value inside ThemeContext.Provider', () => {
    const mockValue = {
      mode: 'dark' as const,
      resolved: 'dark' as const,
      setMode: vi.fn(),
      presetId: 'claude-warm',
      setPresetId: vi.fn(),
      cssThemes: [],
      activeSource: { kind: 'preset' as const, id: 'claude-warm' },
      setActiveCssTheme: vi.fn(),
      refreshCssThemes: vi.fn(async () => {}),
    };
    const { result } = renderHook(() => useTheme(), {
      wrapper: ({ children }) => createElement(ThemeContext.Provider, { value: mockValue }, children),
    });
    expect(result.current.mode).toBe('dark');
    expect(result.current.presetId).toBe('claude-warm');
  });

  it('formats theme audit summary and JSON (Phase P120)', () => {
    const sample = {
      mode: 'system' as const,
      resolved: 'dark' as const,
      presetId: 'sage-default',
      activeSource: { kind: 'preset' as const, id: 'sage-default' },
      cssThemeCount: 2,
    };
    expect(formatThemeAuditSummary(sample)).toBe(
      'mode=system(dark) · preset=sage-default · source=preset:sage-default · css=2',
    );
    expect(JSON.parse(formatThemeAuditJson(sample))).toEqual(sample);
  });
});
