import { describe, expect, it } from 'vitest';

import {
  formatCardLayoutJson,
  formatCardLayoutSummary,
} from '../Card';

describe('Card audit diagnostics', () => {
  it('formats card layout summary', () => {
    expect(formatCardLayoutSummary()).toBe('header=true · title=true · content=true');
    expect(formatCardLayoutSummary(false, false, true)).toBe(
      'header=false · title=false · content=true',
    );
  });

  it('serializes card layout audit JSON', () => {
    const parsed = JSON.parse(formatCardLayoutJson(true, false, true));
    expect(parsed).toEqual({
      hasHeader: true,
      hasTitle: false,
      hasContent: true,
    });
  });
});
