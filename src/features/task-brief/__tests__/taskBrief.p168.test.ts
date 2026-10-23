import { describe, expect, it } from 'vitest';

import { auditTaskBriefGovernance } from '../taskBrief';

describe('auditTaskBriefGovernance (P168)', () => {
  it('returns compliant governance audit metadata for taskBrief', () => {
    const report = auditTaskBriefGovernance();
    expect(report.module).toBe('src/features/task-brief/taskBrief.ts');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.maxFieldLengthChars).toBe(16000);
    expect(report.supportedFormats).toEqual(['docx', 'xlsx', 'pptx', 'pdf', 'markdown']);
    expect(report.compliant).toBe(true);
  });
});
