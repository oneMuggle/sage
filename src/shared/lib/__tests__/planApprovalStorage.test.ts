// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';

import { isPlanApprovalPending, setPlanApprovalPending } from '../planApprovalStorage';

describe('planApprovalStorage', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('默认无待批准计划', () => {
    expect(isPlanApprovalPending('s-1')).toBe(false);
  });

  it('标记后按会话恢复，清除后消失', () => {
    setPlanApprovalPending('s-1', true);
    setPlanApprovalPending('s-2', true);

    expect(isPlanApprovalPending('s-1')).toBe(true);
    expect(isPlanApprovalPending('s-2')).toBe(true);

    setPlanApprovalPending('s-1', false);

    expect(isPlanApprovalPending('s-1')).toBe(false);
    expect(isPlanApprovalPending('s-2')).toBe(true);
  });

  it('sessionId 为空时安全 no-op', () => {
    setPlanApprovalPending(null, true);
    expect(isPlanApprovalPending(null)).toBe(false);
  });
});
