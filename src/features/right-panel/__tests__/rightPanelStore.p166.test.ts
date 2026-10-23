import { describe, expect, it } from 'vitest';

import { auditRightPanelStoreGovernance } from '../rightPanelStore';

describe('auditRightPanelStoreGovernance (P166)', () => {
  it('returns compliant governance audit metadata for rightPanelStore', () => {
    const report = auditRightPanelStoreGovernance();
    expect(report.module).toBe('src/features/right-panel/rightPanelStore.ts');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('right-panel');
    expect(report.tabs).toEqual(['artifacts', 'changes', 'office']);
    expect(report.supportsAutoOpenArtifactGuard).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
