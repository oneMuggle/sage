import { describe, expect, it } from 'vitest';

import { evaluateTaskModelAdvisorGovernanceAudit } from '../TaskModelAdvisor';

describe('evaluateTaskModelAdvisorGovernanceAudit (Phase P140)', () => {
  it('returns healthy report for valid model recommendation with confidence and rationale', () => {
    const report = evaluateTaskModelAdvisorGovernanceAudit({
      recommendedModelId: 'claude-3-7-sonnet',
      confidenceScore: 0.92,
      rationaleText: 'High reasoning accuracy for multi-file TypeScript refactors.',
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedModelId).toBe('claude-3-7-sonnet');
    expect(report.clampedConfidence).toBe(0.92);
    expect(report.hasRationale).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty model ID, out-of-range confidence, and empty rationale', () => {
    const report = evaluateTaskModelAdvisorGovernanceAudit({
      recommendedModelId: '   ',
      confidenceScore: 1.5,
      rationaleText: '',
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'TASK_MODEL_ADVISOR_MODEL_EMPTY',
      'TASK_MODEL_ADVISOR_CONFIDENCE_OUT_OF_RANGE',
      'TASK_MODEL_ADVISOR_RATIONALE_EMPTY',
    ]);
  });
});
