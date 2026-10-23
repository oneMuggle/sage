import { describe, expect, it } from 'vitest';

import { auditTerminalPanelStoreGovernance } from '../terminalPanelStore';

describe('auditTerminalPanelStoreGovernance (P169)', () => {
  it('returns compliant governance audit metadata for terminalPanelStore', () => {
    const report = auditTerminalPanelStoreGovernance();
    expect(report.module).toBe('src/features/terminal-panel/terminalPanelStore.ts');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('terminal-panel');
    expect(report.minHeightPx).toBeGreaterThan(0);
    expect(report.maxHeightPx).toBeGreaterThan(report.minHeightPx);
    expect(report.compliant).toBe(true);
  });
});
