import { describe, expect, it } from 'vitest';

import { auditTodoPageGovernance } from '../TodoPage';

describe('auditTodoPageGovernance (P171)', () => {
  it('returns compliant governance audit metadata for TodoPage', () => {
    const report = auditTodoPageGovernance();
    expect(report.module).toBe('src/pages/TodoPage.tsx');
    expect(report.phase).toBe('P171');
    expect(report.domain).toBe('pages');
    expect(report.supportsCompleteCancelAndTwoStepDelete).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
