import { describe, expect, it } from 'vitest';

import { auditOfficePageGovernance } from '../../Office';

describe('Office P142 governance audit', () => {
  it('returns healthy defaults for Office page governance', () => {
    const res = auditOfficePageGovernance();
    expect(res.module).toBe('src/pages/Office.tsx');
    expect(res.phase).toBe('P142');
    expect(res.activeMode).toBe('generate');
    expect(res.documentFormat).toBe('ppt');
    expect(res.isGenerating).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('normalizes activeMode and documentFormat', () => {
    const res = auditOfficePageGovernance({
      activeMode: 'edit',
      documentFormat: 'docx',
      isGenerating: true,
    });
    expect(res.activeMode).toBe('edit');
    expect(res.documentFormat).toBe('docx');
    expect(res.isGenerating).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
