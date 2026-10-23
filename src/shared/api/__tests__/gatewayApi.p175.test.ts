import { describe, expect, it } from 'vitest';

import { auditGatewayApiGovernance } from '../gatewayApi';

describe('auditGatewayApiGovernance (P175)', () => {
  it('returns compliant governance audit metadata for gatewayApi', () => {
    const report = auditGatewayApiGovernance();
    expect(report.module).toBe('src/shared/api/gatewayApi.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.platforms).toEqual(['telegram', 'feishu', 'dingtalk', 'wecom', 'qq']);
    expect(report.compliant).toBe(true);
  });
});
