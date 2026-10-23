import { describe, expect, it } from 'vitest';

import {
  auditUseFeatureUnlockGovernance,
  formatFeatureUnlockJson,
  formatFeatureUnlockSummary,
} from '../useFeatureUnlock';

describe('useFeatureUnlock P181 governance audit', () => {
  it('audits useFeatureUnlock governance contract and feature unlock formatters', () => {
    const raw = auditUseFeatureUnlockGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.hooks.use_feature_unlock.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.sampleSummary).toContain('p181.probe');
    expect(formatFeatureUnlockSummary('demo.key')).toContain('demo.key ·');
    expect(JSON.parse(formatFeatureUnlockJson('demo.key')).featureKey).toBe('demo.key');
  });
});
