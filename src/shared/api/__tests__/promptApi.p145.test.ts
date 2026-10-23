import { describe, expect, it } from 'vitest';

import { auditPromptApiGovernance } from '../promptApi';

describe('promptApi P145 governance audit', () => {
  it('returns healthy defaults for promptApi governance', () => {
    const res = auditPromptApiGovernance();
    expect(res.module).toBe('src/shared/api/promptApi.ts');
    expect(res.phase).toBe('P145');
    expect(res.templateCount).toBe(6);
    expect(res.supportsCustomVariables).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes templateCount and custom variables flag', () => {
    const res = auditPromptApiGovernance({
      templateCount: 11.8,
      supportsCustomVariables: false,
    });
    expect(res.templateCount).toBe(11);
    expect(res.supportsCustomVariables).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
