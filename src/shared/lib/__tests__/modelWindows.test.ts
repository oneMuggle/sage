import { describe, expect, it } from 'vitest';

import {
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  formatModelWindowSummary,
  formatModelWindowJson,
} from '../modelWindows';

describe('modelWindows audit helpers', () => {
  it('resolves effective window and history budget summary and json', () => {
    expect(formatModelWindowSummary(128000, null, true, 16000)).toBe(
      'window=128000 · budget=112000 · auto=true',
    );
    const parsed = JSON.parse(formatModelWindowJson(128000, 64000, false, 16000));
    expect(parsed).toEqual({
      effectiveWindow: 64000,
      historyBudget: 48000,
      autoContext: false,
      reserve: 16000,
    });
  });

  it('falls back to default window when catalog window is unknown', () => {
    expect(formatModelWindowSummary(null)).toBe(
      `window=${DEFAULT_CONTEXT_WINDOW_TOKENS} · budget=0 · auto=true`,
    );
    expect(JSON.parse(formatModelWindowJson(undefined)).effectiveWindow).toBe(
      DEFAULT_CONTEXT_WINDOW_TOKENS,
    );
  });
});
