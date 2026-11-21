import { describe, expect, it } from 'vitest';

import { composeReviewFeedback } from '../designReview';

describe('composeReviewFeedback', () => {
  it('formats P0 and P1 issues into iterate feedback', () => {
    const feedback = composeReviewFeedback({
      ok: false,
      error_count: 1,
      warning_count: 1,
      issues: [
        {
          rule_id: 'no_default_indigo',
          severity: 'error',
          message: 'indigo accent',
        },
        {
          rule_id: 'no_ai_buzzwords',
          severity: 'warning',
          message: 'buzzword found',
        },
      ],
    });

    expect(feedback).toContain('请修复以下设计质量问题');
    expect(feedback).toContain('- [P0] no_default_indigo: indigo accent');
    expect(feedback).toContain('- [P1] no_ai_buzzwords: buzzword found');
  });

  it('returns an empty string when there are no issues', () => {
    const feedback = composeReviewFeedback({
      ok: true,
      error_count: 0,
      warning_count: 0,
      issues: [],
    });
    expect(feedback).toBe('');
  });
});
