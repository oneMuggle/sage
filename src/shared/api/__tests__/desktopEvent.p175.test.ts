import { describe, expect, it } from 'vitest';

import { auditDesktopEventGovernance } from '../desktopEvent';

describe('auditDesktopEventGovernance (P175)', () => {
  it('returns compliant governance audit metadata for desktopEvent', () => {
    const report = auditDesktopEventGovernance();
    expect(report.module).toBe('src/shared/api/desktopEvent.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.supportsStreamIdUnlistenPropagation).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
