import { describe, expect, it } from 'vitest';

import {
  auditProductMessagesGovernance,
  formatProductMessagesJson,
  formatProductMessagesSummary,
  productMessages,
} from '../productMessages';

describe('productMessages P179 governance audit', () => {
  it('audits productMessages governance contract and locale parity', () => {
    const raw = auditProductMessagesGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.product_messages.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.locales).toEqual(['zh', 'en']);
    expect(productMessages('en').saved).toBe('Save confirmed');
    expect(formatProductMessagesSummary('zh')).toContain('parity=true');
    expect(JSON.parse(formatProductMessagesJson('en')).parity).toBe(true);
  });
});
