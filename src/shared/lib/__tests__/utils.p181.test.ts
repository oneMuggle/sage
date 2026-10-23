import { describe, expect, it } from 'vitest';

import {
  auditUtilsGovernance,
  formatTextTruncateJson,
  formatTextTruncateSummary,
  truncate,
} from '../utils';

describe('utils P181 governance audit', () => {
  it('audits utils governance contract and text truncate helpers', () => {
    const raw = auditUtilsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.utils.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.sampleTruncate).toBe('Hello...');
    expect(truncate('abc', 5)).toBe('abc');
    expect(formatTextTruncateSummary('abcdef', 3)).toBe('length=6 · max=3 · truncated=true');
    expect(JSON.parse(formatTextTruncateJson('abcdef', 3)).preview).toBe('abc...');
  });
});
