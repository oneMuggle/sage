import { describe, expect, it } from 'vitest';

import {
  auditOfficeStagingInspectorGovernance,
  formatOfficeStagingJson,
  formatOfficeStagingMarkdown,
} from '../OfficeStagingInspector';

describe('OfficeStagingInspector governance audit (P165)', () => {
  it('returns ready governance status for OfficeStagingInspector', () => {
    const snap = auditOfficeStagingInspectorGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeStagingInspector.tsx',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('formats office staging markdown and json when report is null', () => {
    expect(formatOfficeStagingMarkdown('/ws', null)).toContain('_尚未执行暂存区检查_');
    expect(JSON.parse(formatOfficeStagingJson('/ws', null))).toMatchObject({
      workspacePath: '/ws',
      report: null,
    });
  });
});
