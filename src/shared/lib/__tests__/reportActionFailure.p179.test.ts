import { describe, expect, it } from 'vitest';

import {
  auditReportActionFailureGovernance,
  formatActionError,
  formatActionFailureJson,
  formatActionFailureSummary,
} from '../reportActionFailure';

describe('reportActionFailure P179 governance audit', () => {
  it('audits reportActionFailure governance contract and error formatters', () => {
    const raw = auditReportActionFailureGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.report_action_failure.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.defaultFallback).toBe('操作失败');
    expect(formatActionError(new Error('boom'))).toBe('boom');
    expect(formatActionFailureSummary('测试', '失败')).toBe('测试 · 失败');
    expect(JSON.parse(formatActionFailureJson('测试', '失败')).detail).toBe('失败');
  });
});
