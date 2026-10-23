import { describe, expect, it } from 'vitest';

import {
  auditFileLangGovernance,
  formatFileLangJson,
  formatFileLangSummary,
  langFromPath,
} from '../fileLang';

describe('fileLang P178 governance audit', () => {
  it('audits fileLang governance contract and extension mapping helpers', () => {
    const raw = auditFileLangGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.file_lang.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.supportedExtensionsCount).toBeGreaterThan(20);
    expect(langFromPath('main.py')).toBe('python');
    expect(formatFileLangSummary('main.py')).toBe('path=main.py · lang=python');
    expect(JSON.parse(formatFileLangJson('main.py')).recognized).toBe(true);
  });
});
