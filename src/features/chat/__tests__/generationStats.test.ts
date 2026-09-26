// 对话阅读体验第二轮 C1：生成速度计算与格式化。
import { describe, expect, it } from 'vitest';

import { formatCount, formatDuration, formatRate, tokensPerSecond } from '../generationStats';

describe('tokensPerSecond', () => {
  it('excludes the time to first token from the generation window', () => {
    // 30 tokens over (1500 - 250) ms = 24 tok/s
    expect(tokensPerSecond({ output_tokens: 30, first_token_ms: 250, latency_ms: 1500 })).toBe(24);
  });

  it('falls back to the total latency without a first-token time', () => {
    expect(tokensPerSecond({ output_tokens: 10, latency_ms: 2000 })).toBe(5);
    // 首字延迟不合理（≥ 总耗时）时同样按总耗时计算
    expect(tokensPerSecond({ output_tokens: 10, first_token_ms: 2000, latency_ms: 2000 })).toBe(5);
  });

  it('returns null without usage or timing', () => {
    expect(tokensPerSecond(null)).toBeNull();
    expect(tokensPerSecond({ latency_ms: 1000 })).toBeNull();
    expect(tokensPerSecond({ output_tokens: 10 })).toBeNull();
    expect(tokensPerSecond({ output_tokens: 0, latency_ms: 1000 })).toBeNull();
  });
});

describe('formatting', () => {
  it('formats durations by magnitude', () => {
    expect(formatDuration(820)).toBe('0.82s');
    expect(formatDuration(12_440)).toBe('12.4s');
    expect(formatDuration(125_000)).toBe('2m05s');
    expect(formatDuration(119_600)).toBe('2m00s');
  });

  it('formats rates and counts', () => {
    expect(formatRate(42.345)).toBe('42.3');
    expect(formatRate(123.6)).toBe('124');
    expect(formatCount(1234, 'zh')).toBe('1,234');
    expect(formatCount(1234, 'en')).toBe('1,234');
  });
});
