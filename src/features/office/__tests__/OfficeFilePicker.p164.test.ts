import { describe, expect, it } from 'vitest';

import {
  auditOfficeFilePickerGovernance,
  formatOfficePickerJson,
  formatOfficePickerMarkdown,
} from '../OfficeFilePicker';

describe('OfficeFilePicker governance audit (P164)', () => {
  it('returns ready governance status for OfficeFilePicker', () => {
    const snap = auditOfficeFilePickerGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeFilePicker.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats office file picker markdown and json', () => {
    const params = {
      docType: 'word' as const,
      workspacePath: '/ws',
      disabled: false,
      error: null,
    };
    expect(formatOfficePickerMarkdown(params)).toContain('Word (.docx)');
    expect(JSON.parse(formatOfficePickerJson(params))).toMatchObject({
      docType: 'word',
      workspacePath: '/ws',
      disabled: false,
    });
  });
});
