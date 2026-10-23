import { describe, expect, it } from 'vitest';

import {
  auditOfficeDocumentListGovernance,
  formatOfficeDocumentListJson,
  formatOfficeDocumentListMarkdown,
} from '../OfficeDocumentList';

describe('OfficeDocumentList governance audit (P164)', () => {
  it('returns ready governance status for OfficeDocumentList', () => {
    const snap = auditOfficeDocumentListGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeDocumentList.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats empty office document list markdown and json', () => {
    expect(formatOfficeDocumentListMarkdown([], 'live')).toContain('_暂无历史文档_');
    expect(JSON.parse(formatOfficeDocumentListJson([], 'archived'))).toMatchObject({
      variant: 'archived',
      total: 0,
    });
  });
});
