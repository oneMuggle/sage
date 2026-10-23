import { describe, expect, it } from 'vitest';

import { auditTaskBriefDialogGovernance } from '../TaskBriefDialog';

describe('auditTaskBriefDialogGovernance (P168)', () => {
  it('returns compliant governance audit metadata for TaskBriefDialog', () => {
    const report = auditTaskBriefDialogGovernance();
    expect(report.module).toBe('src/features/task-brief/TaskBriefDialog.tsx');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.supportsDraftRecipeSave).toBe(true);
    expect(report.supportsModelAdvisorIntegration).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
