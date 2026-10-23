import { describe, it, expect } from 'vitest';

import { AGENT_RUNTIME_MESSAGES, mapAgentErrorToText, mapLLMErrorToText, parseAgentErrorLimit, type LLMErrorResponse } from './errorMapping';

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

describe('parseAgentErrorLimit', () => {
  it('splits the wire format into code and limit', () => {
    const parsed = parseAgentErrorLimit('max_iterations_exceeded (limit=25)');

    expect(parsed).not.toBeNull();
    expect(parsed?.code).toBe('max_iterations_exceeded');
    expect(parsed?.value).toBe(25);
    expect(parsed?.text).toBe('25');
  });

  it('parses the tool budget ceiling', () => {
    const parsed = parseAgentErrorLimit('tool_budget_exceeded (limit=100)');

    expect(parsed?.code).toBe('tool_budget_exceeded');
    expect(parsed?.value).toBe(100);
  });

  it('keeps the decimal precision of money limits', () => {
    const parsed = parseAgentErrorLimit('spend_limit_exceeded (limit=50.00)');

    expect(parsed?.value).toBe(50);
    // 原始文本保留两位小数，渲染时不被截成 "50"
    expect(parsed?.text).toBe('50.00');
  });

  it('returns null for a bare code without limit decoration', () => {
    expect(parseAgentErrorLimit('max_iterations_exceeded')).toBeNull();
  });

  it('returns null for non-wire text', () => {
    expect(parseAgentErrorLimit('今日花费已达限额')).toBeNull();
    expect(parseAgentErrorLimit('some error (code=1)')).toBeNull();
  });

  it('returns null for empty input', () => {
    expect(parseAgentErrorLimit('')).toBeNull();
  });
});

describe('mapAgentErrorToText — limit rendering', () => {
  it('renders the iteration ceiling with its unit', () => {
    const text = mapAgentErrorToText('max_iterations_exceeded (limit=25)');

    expect(text).toContain('25');
    expect(text).toContain('次');
    expect(text).not.toContain('{limit}');
    expect(text).not.toContain('max_iterations_exceeded');
  });

  it('renders the tool budget ceiling', () => {
    const text = mapAgentErrorToText('tool_budget_exceeded (limit=100)');

    expect(text).toContain('100');
    expect(text).not.toContain('{limit}');
  });

  it('renders the subagent iteration ceiling', () => {
    const text = mapAgentErrorToText('subagent_exhausted_iterations (limit=6)');

    expect(text).toContain('6');
    expect(text).not.toContain('{limit}');
  });

  it('strips the placeholder for bare codes so it never leaks to users', () => {
    const text = mapAgentErrorToText('max_iterations_exceeded');

    expect(text).toBeTruthy();
    expect(text).not.toContain('{limit}');
  });

  it('does not treat inherited Object properties as known codes', () => {
    // 装饰后的畸形码同样必须返回 null，不能拿到 Object 构造函数
    expect(mapAgentErrorToText('constructor (limit=1)')).toBeNull();
    expect(mapAgentErrorToText('toString (limit=1)')).toBeNull();
  });

  it('returns null for an unknown decorated code', () => {
    expect(mapAgentErrorToText('some_future_code (limit=1)')).toBeNull();
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

  it('formats LLM error summary and JSON (Phase P118)', async () => {
    const { formatLLMErrorSummary, formatLLMErrorJson } = await import('./errorMapping');
    const sample = err({ type: 'rate_limited', status_code: 429, retry_after: 15 });
    expect(formatLLMErrorSummary(sample)).toContain('rate_limited · status=429 · retry=15');
    const parsed = JSON.parse(formatLLMErrorJson(sample));
    expect(parsed.type).toBe('rate_limited');
    expect(parsed.statusCode).toBe(429);
    expect(parsed.retryAfter).toBe(15);
  });
});
