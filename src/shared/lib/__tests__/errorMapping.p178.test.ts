import { describe, expect, it } from 'vitest';

import {
  auditErrorMappingGovernance,
  formatLLMErrorJson,
  formatLLMErrorSummary,
  mapAgentErrorToText,
} from '../errorMapping';

describe('errorMapping P178 governance audit', () => {
  it('audits errorMapping governance contract and LLM/agent error mappers', () => {
    const raw = auditErrorMappingGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.error_mapping.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.runtimeErrorCodes).toContain('max_iterations_exceeded');
    expect(mapAgentErrorToText('tool_budget_exceeded')).toBeTruthy();
    const err = {
      type: 'auth_failed' as const,
      message: 'Unauthorized',
      status_code: 401,
      retry_after: null,
    };
    expect(formatLLMErrorSummary(err)).toContain('auth_failed · status=401');
    expect(JSON.parse(formatLLMErrorJson(err)).statusCode).toBe(401);
  });
});

describe('errorMapping — 动态预算 source (M5)', () => {
  it('source=dynamic 时展示「动态预算」标签并指引到预算模式设置', () => {
    const text = mapAgentErrorToText('max_iterations_exceeded (limit=280, source=dynamic)');
    expect(text).toContain('上限来源：动态预算');
    expect(text).toContain('「设置 → 编排 → 预算模式」');
    // 不应把用户引到错误的"迭代次数上限"设置项
    expect(text).not.toContain('Agent 迭代次数上限」调高');
  });
});
