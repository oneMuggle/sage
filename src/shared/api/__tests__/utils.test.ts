/**
 * r97: utils 单测——sanitizeInput/isValidSessionId/withRetry/handleApiError 契约锁定。
 */
import { describe, expect, it, vi } from 'vitest';

import { ApiException, handleApiError, isValidSessionId, sanitizeInput, withRetry } from '../utils';

describe('sanitizeInput', () => {
  it('转义 HTML 特殊字符（含斜杠）', () => {
    // 替换顺序 & → < → > → " → ' → /（& 先行保证不二次转义）
    expect(sanitizeInput("<'&/\">")).toBe('&lt;&#x27;&amp;&#x2F;&quot;&gt;');
    expect(sanitizeInput('<b>bold</b>')).toBe('&lt;b&gt;bold&lt;&#x2F;b&gt;');
  });

  it('非字符串输入返回空串', () => {
    expect(sanitizeInput(undefined as never)).toBe('');
    expect(sanitizeInput(null as never)).toBe('');
  });
});

describe('isValidSessionId', () => {
  it('接受标准 UUID（大小写不敏感）', () => {
    expect(isValidSessionId('12345678-1234-1234-1234-123456789abc')).toBe(true);
    expect(isValidSessionId('ABCDEF01-2345-6789-ABCD-EF0123456789')).toBe(true);
  });

  it('拒绝缺段/超长/非法字符', () => {
    expect(isValidSessionId('short')).toBe(false);
    expect(isValidSessionId('12345678123412341234123456789abc')).toBe(false);
    expect(isValidSessionId('12345678-1234-1234-1234-123456789abg')).toBe(false);
    expect(isValidSessionId('')).toBe(false);
  });
});

describe('withRetry', () => {
  it('首次成功只调用一次', async () => {
    const op = vi.fn().mockResolvedValue('ok');
    await expect(withRetry(op)).resolves.toBe('ok');
    expect(op).toHaveBeenCalledTimes(1);
  });

  it('失败后重试直至成功', async () => {
    vi.useFakeTimers();
    try {
      const op = vi.fn()
        .mockRejectedValueOnce(new Error('a'))
        .mockRejectedValueOnce(new Error('b'))
        .mockResolvedValueOnce('done');
      const p = withRetry(op);
      const settled = p.then((v) => ({ ok: true as const, v }), (e) => ({ ok: false as const, e }));
      // 1s + 2s 退避
      await vi.advanceTimersByTimeAsync(4_000);
      const r = await settled;
      expect(r.ok).toBe(true);
      expect(op).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('耗尽重试抛最后错误，maxRetries=0 只调用一次', async () => {
    vi.useFakeTimers();
    try {
      const op = vi.fn().mockRejectedValue(new Error('always fails'));
      const p = withRetry(op, { maxRetries: 0 });
      const settled = p.then((v) => ({ ok: true as const, v }), (e) => ({ ok: false as const, e }));
      await vi.advanceTimersByTimeAsync(1_000);
      const r = await settled;
      expect(r.ok).toBe(false);
      expect((r as { e: Error }).e.message).toBe('always fails');
      expect(op).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('handleApiError', () => {
  it('ApiException 原样透传（同一实例）', () => {
    const original = new ApiException({ error: 'E1', message: 'm' });
    expect(handleApiError(original)).toBe(original);
  });

  it('结构化错误取 error/message 字段', () => {
    const wrapped = handleApiError({ error: 'NOT_FOUND', message: 'missing' });
    expect(wrapped).toBeInstanceOf(ApiException);
    expect(wrapped.code).toBe('NOT_FOUND');
    expect(wrapped.message).toBe('missing');
  });

  it('内层 LLM 错误（带 type）保留完整 llmError', () => {
    const llm = { type: 'rate_limit', message: 'slow down' };
    const wrapped = handleApiError({ error: llm, message: 'upstream' });
    expect(wrapped.code).toBe('rate_limit');
    expect(wrapped.message).toBe('upstream');
    expect(wrapped.llmError).toEqual(llm);
  });

  it('未知错误包装 UNKNOWN_ERROR：Error 取 message，非字符串进 details', () => {
    const fromError = handleApiError(new Error('boom'));
    expect(fromError.code).toBe('UNKNOWN_ERROR');
    expect(fromError.message).toBe('boom');

    const fromString = handleApiError('weird');
    expect(fromString.code).toBe('UNKNOWN_ERROR');
    expect(fromString.message).toBe('未知错误');
    expect(fromString.details).toEqual({ originalError: 'weird' });
  });
});
