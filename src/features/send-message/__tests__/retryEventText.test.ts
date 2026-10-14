import { describe, expect, it } from 'vitest';

import type { RetryInfo } from '../../../shared/api/types/chatAndEventTypes';
import { formatRetryEventText } from '../retryEventText';

function makeInfo(overrides: Partial<RetryInfo> = {}): RetryInfo {
  return {
    attempt: 2,
    max_attempts: 3,
    error_type: 'timeout',
    error_message: 'read timed out',
    delay: 2,
    ...overrides,
  };
}

describe('formatRetryEventText', () => {
  it('renders attempt/max_attempts with the Chinese reason label', () => {
    expect(formatRetryEventText(makeInfo())).toBe('🔄 重试中 (2/3) | 原因: 请求超时 | 等待 2秒');
  });

  it('rounds delays of 1s or more to an integer', () => {
    expect(formatRetryEventText(makeInfo({ delay: 2.6 }))).toContain('等待 3秒');
  });

  it('keeps one decimal place for sub-second delays', () => {
    expect(formatRetryEventText(makeInfo({ delay: 0.5 }))).toContain('等待 0.5秒');
  });

  it('passes unknown error types through instead of swallowing them', () => {
    expect(formatRetryEventText(makeInfo({ error_type: 'brand_new_error' }))).toContain(
      '原因: brand_new_error',
    );
  });

  it('labels every known error type', () => {
    const labels: Record<string, string> = {
      network_error: '网络错误',
      server_error: '服务端错误',
      rate_limited: '频率限制',
      auth_failed: '认证失败',
      parsing_error: '响应解析失败',
      context_overflow: '上下文溢出',
      unknown: '未知错误',
    };
    for (const [errorType, label] of Object.entries(labels)) {
      expect(formatRetryEventText(makeInfo({ error_type: errorType }))).toContain(`原因: ${label}`);
    }
  });
});