import { describe, expect, it } from 'vitest';

import { auditMessageApiGovernance } from '../messageApi';

describe('messageApi P144 governance audit', () => {
  it('returns healthy defaults for messageApi governance', () => {
    const res = auditMessageApiGovernance();
    expect(res.module).toBe('src/shared/api/messageApi.ts');
    expect(res.phase).toBe('P144');
    expect(res.endpointCount).toBe(2);
    expect(res.supportsFeedback).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes endpointCount and supportsFeedback', () => {
    const res = auditMessageApiGovernance({
      endpointCount: 0,
      supportsFeedback: false,
    });
    expect(res.endpointCount).toBe(0);
    expect(res.supportsFeedback).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
