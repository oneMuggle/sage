import { describe, expect, it } from 'vitest';

import {
  ATTENTION_KINDS,
  auditAttentionCenterGovernance,
} from '../attentionCenter';

describe('attentionCenter P158 governance audit', () => {
  it('returns healthy defaults for attentionCenter governance', () => {
    const res = auditAttentionCenterGovernance();
    expect(res.module).toBe('src/features/attention/attentionCenter.ts');
    expect(res.phase).toBe('P158');
    expect(res.kindCount).toBe(ATTENTION_KINDS.length);
    expect(res.totalCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when totalCount exceeds 500', () => {
    const res = auditAttentionCenterGovernance({ totalCount: 600 });
    expect(res.totalCount).toBe(600);
    expect(res.healthy).toBe(false);
  });
});
