import { describe, expect, it } from 'vitest';

import {
  formatModalDialogJson,
  formatModalDialogSummary,
} from '../Modal';

describe('Modal audit diagnostics', () => {
  it('formats modal dialog state summary', () => {
    expect(formatModalDialogSummary(true, true, true)).toBe(
      'open=true · title=true · footer=true',
    );
    expect(formatModalDialogSummary(false, false, false)).toBe(
      'open=false · title=false · footer=false',
    );
  });

  it('serializes modal dialog audit JSON', () => {
    const parsed = JSON.parse(formatModalDialogJson(true, true, false));
    expect(parsed).toEqual({
      isOpen: true,
      hasTitle: true,
      hasFooter: false,
    });
  });
});
