import { describe, expect, it } from 'vitest';

import { officeAiSidebarEn, officeAiSidebarZh } from '../officeAiSidebar';

describe('officeAiSidebar i18n', () => {
  it('has identical key sets in zh and en', () => {
    expect(Object.keys(officeAiSidebarZh).sort()).toEqual(Object.keys(officeAiSidebarEn).sort());
  });

  it('has no empty strings', () => {
    for (const [key, value] of Object.entries({
      ...officeAiSidebarZh,
      ...officeAiSidebarEn,
    })) {
      expect(value.trim(), key).not.toBe('');
    }
  });
});
