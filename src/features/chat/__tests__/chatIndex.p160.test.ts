import { describe, expect, it } from 'vitest';

import {
  auditChatFeatureBarrelGovernance,
  formatChatFeatureBarrelJson,
  formatChatFeatureBarrelSummary,
} from '../index';

describe('chat index barrel Phase P160 governance audit', () => {
  it('audits chat feature barrel governance metadata', () => {
    const audit = auditChatFeatureBarrelGovernance('sess-p160', 'product-delivery');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/index.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('product-delivery');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 ChatFeatureBarrel Governance');
  });

  it('preserves existing barrel summary and JSON helpers', () => {
    expect(formatChatFeatureBarrelSummary()).toContain('chat');
    expect(formatChatFeatureBarrelJson()).toContain('features/chat');
    const fallback = auditChatFeatureBarrelGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
