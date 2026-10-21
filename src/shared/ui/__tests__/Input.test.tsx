import { describe, expect, it } from 'vitest';

import {
  formatInputFieldJson,
  formatInputFieldSummary,
} from '../Input';

describe('Input audit diagnostics', () => {
  it('formats input field state summary', () => {
    expect(formatInputFieldSummary()).toBe('error=false · disabled=false');
    expect(formatInputFieldSummary(true, true)).toBe('error=true · disabled=true');
  });

  it('serializes input field audit JSON', () => {
    const parsed = JSON.parse(formatInputFieldJson(true, false));
    expect(parsed).toEqual({
      error: true,
      disabled: false,
    });
  });
});
