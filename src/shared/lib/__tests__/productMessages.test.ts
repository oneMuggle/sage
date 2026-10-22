import { describe, expect, it } from 'vitest';

import {
  formatProductMessagesJson,
  formatProductMessagesSummary,
  productMessages,
} from '../productMessages';

describe('productMessages audit diagnostics', () => {
  it('resolves locale messages and formats summary', () => {
    expect(productMessages('zh').saved).toBe('已确认保存');
    expect(productMessages('en').saved).toBe('Save confirmed');
    expect(formatProductMessagesSummary('zh')).toBe('locale=zh · keys=8 · parity=true');
    expect(formatProductMessagesSummary('en')).toBe('locale=en · keys=8 · parity=true');
  });

  it('serializes product messages audit JSON', () => {
    const parsed = JSON.parse(formatProductMessagesJson('en'));
    expect(parsed.locale).toBe('en');
    expect(parsed.keyCount).toBe(8);
    expect(parsed.parity).toBe(true);
    expect(parsed.keys).toContain('taskSummary');
  });
});
