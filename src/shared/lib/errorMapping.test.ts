import { describe, it, expect } from 'vitest';

import {
  AGENT_RUNTIME_MESSAGES,
  mapAgentErrorToText,
  mapLLMErrorToText,
  type LLMErrorResponse,
} from './errorMapping';

describe('mapAgentErrorToText', () => {
  it('maps max_iterations_exceeded to actionable Chinese text', () => {
    const text = mapAgentErrorToText('max_iterations_exceeded');

    expect(text).toBeTruthy();
    // 必须是中文（而非后端裸码），且指出可调整的去处
    expect(text).toMatch(/迭代/);
    expect(text).not.toMatch(/max_iterations_exceeded/);
  });

  it('maps the other agent runtime codes', () => {
    expect(mapAgentErrorToText('tool_budget_exceeded')).toBeTruthy();
    expect(mapAgentErrorToText('subagent_loop_failed')).toBeTruthy();
  });

  it('returns null for unknown codes so callers keep original behaviour', () => {
    expect(mapAgentErrorToText('some_future_code')).toBeNull();
    expect(mapAgentErrorToText('')).toBeNull();
  });

  it('does not treat inherited Object properties as known codes', () => {
    // 防御原型链：'constructor' / 'toString' 不是合法错误码
    expect(mapAgentErrorToText('constructor')).toBeNull();
    expect(mapAgentErrorToText('toString')).toBeNull();
  });

  it('every message in the table is non-empty Chinese text', () => {
    const entries = Object.entries(AGENT_RUNTIME_MESSAGES);
    expect(entries.length).toBeGreaterThan(0);
    for (const [code, msg] of entries) {
      expect(msg.length, code).toBeGreaterThan(0);
      expect(msg, code).toMatch(/[一-龥]/);
    }
  });
});

describe('mapLLMErrorToText (regression — agent codes must not leak in)', () => {
  const err = (over: Partial<LLMErrorResponse> = {}): LLMErrorResponse => ({
    type: 'auth_failed',
    message: 'raw',
    status_code: null,
    retry_after: null,
    ...over,
  });

  it('keeps existing LLM transport mappings intact', () => {
    expect(mapLLMErrorToText(err({ type: 'auth_failed' }))).toMatch(/API Key/);
    expect(mapLLMErrorToText(err({ type: 'network_error' }))).toMatch(/网络/);
    expect(mapLLMErrorToText(err({ type: 'timeout' }))).toMatch(/超时/);
  });

  it('still appends retry_after hint for rate_limited', () => {
    const text = mapLLMErrorToText(err({ type: 'rate_limited', retry_after: 30 }));
    expect(text).toMatch(/30/);
  });
});
