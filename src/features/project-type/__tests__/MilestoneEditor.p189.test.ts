import { describe, expect, it } from 'vitest';

import { auditMilestoneEditorGovernance } from '../MilestoneEditor';

describe('auditMilestoneEditorGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditMilestoneEditorGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('milestone-editor');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
