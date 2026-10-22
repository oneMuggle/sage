import { describe, expect, it } from 'vitest';

import {
  MESSAGE_JUMP_TTL_MS,
  auditMessageJumpStoreGovernance,
  buildMessageJumpStoreAuditJson,
} from '../messageJumpStore';

describe('messageJumpStore Phase P160 governance audit', () => {
  it('audits messageJumpStore governance metadata', () => {
    const audit = auditMessageJumpStoreGovernance('sess-p160', 'operations');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/messageJumpStore.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('operations');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 MessageJumpStore Governance');
  });

  it('preserves TTL constant and audit JSON helper', () => {
    expect(MESSAGE_JUMP_TTL_MS).toBeGreaterThan(0);
    expect(buildMessageJumpStoreAuditJson()).toContain('ttlMs');
    const fallback = auditMessageJumpStoreGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
