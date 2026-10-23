import { describe, expect, it } from 'vitest';

import {
  auditEndpointStatusGovernance,
  formatEndpointIssueJson,
  formatEndpointIssueSummary,
  isSameEndpoint,
} from '../endpointStatus';

describe('endpointStatus P178 governance audit', () => {
  it('audits endpointStatus governance contract and endpoint helpers', () => {
    const raw = auditEndpointStatusGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.endpoint_status.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.healthySummary).toBe('healthy');
    expect(parsed.supportsEndpointComparison).toBe(true);
    expect(isSameEndpoint('http://localhost:8765/', 'http://localhost:8765')).toBe(true);
    expect(formatEndpointIssueSummary(null)).toBe('healthy');
    expect(JSON.parse(formatEndpointIssueJson(null)).healthy).toBe(true);
  });
});
