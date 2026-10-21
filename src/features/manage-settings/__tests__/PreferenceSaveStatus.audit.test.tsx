import { describe, expect, it } from 'vitest';

import {
  formatPreferenceSaveStatusJson,
  formatPreferenceSaveStatusSummary,
} from '../PreferenceSaveStatus';

describe('PreferenceSaveStatus audit helpers', () => {
  it('formats preference save status summary', () => {
    expect(formatPreferenceSaveStatusSummary('idle')).toBe(
      'status=idle · visible=false · role=none',
    );
    expect(formatPreferenceSaveStatusSummary('saved')).toBe(
      'status=saved · visible=true · role=status',
    );
    expect(formatPreferenceSaveStatusSummary('error')).toBe(
      'status=error · visible=true · role=alert',
    );
  });

  it('exports preference save status JSON snapshot', () => {
    expect(JSON.parse(formatPreferenceSaveStatusJson('saving'))).toEqual({
      status: 'saving',
      visible: true,
      role: 'status',
    });
  });
});

