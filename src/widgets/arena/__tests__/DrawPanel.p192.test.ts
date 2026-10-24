import { describe, expect, it } from 'vitest';

import { auditDrawPanelGovernance } from '../DrawPanel';

describe('auditDrawPanelGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditDrawPanelGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('draw-panel');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
