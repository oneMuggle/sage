/**
 * P0-A (2026-09-18): 上下文长度档位/单位 helpers 单测
 * (docs/superpowers/specs/2026-09-18-endpoint-quota-model-settings-optimization-design.md §4)
 */
import { describe, expect, it } from 'vitest';

import {
  CONTEXT_MAX_TOKENS,
  CONTEXT_PRESETS,
  clampTokenCount,
  deriveTokenInput,
  formatTokens,
  parseTokenInput,
} from '../contextPresets';

describe('CONTEXT_PRESETS', () => {
  it('覆盖长上下文档位 512K / 1M / 2M', () => {
    const tokens = CONTEXT_PRESETS.map((p) => p.tokens);
    expect(tokens).toContain(524288);
    expect(tokens).toContain(1000000);
    expect(tokens).toContain(2000000);
  });
});

describe('parseTokenInput', () => {
  it('按单位乘数归一化 (512 + K → 512000, 1 + M → 1000000)', () => {
    expect(parseTokenInput('512', 'K')).toBe(512000);
    expect(parseTokenInput('1', 'M')).toBe(1000000);
    expect(parseTokenInput('8192', 'tokens')).toBe(8192);
  });

  it('低于下限钳制到 1024, 高于上限钳制到 10M', () => {
    expect(parseTokenInput('1', 'tokens')).toBe(1024);
    expect(parseTokenInput('99999999', 'M')).toBe(CONTEXT_MAX_TOKENS);
  });

  it('非法输入返回 0 (调用方据此跳过写回)', () => {
    expect(parseTokenInput('', 'K')).toBe(0);
    expect(parseTokenInput('abc', 'K')).toBe(0);
    expect(parseTokenInput('-5', 'M')).toBe(0);
  });
});

describe('clampTokenCount', () => {
  it('四舍五入 + 区间钳制; 非正数返回 0', () => {
    expect(clampTokenCount(4096.4)).toBe(4096);
    expect(clampTokenCount(4096.6)).toBe(4097);
    expect(clampTokenCount(0)).toBe(0);
    expect(clampTokenCount(-1)).toBe(0);
  });
});

describe('deriveTokenInput', () => {
  it('整百万派生 M, 整百以上派生 K, 其它保持 tokens', () => {
    expect(deriveTokenInput(1000000)).toEqual({ text: '1', unit: 'M' });
    expect(deriveTokenInput(8000)).toEqual({ text: '8', unit: 'K' });
    expect(deriveTokenInput(8192)).toEqual({ text: '8192', unit: 'tokens' });
  });
});

describe('formatTokens', () => {
  it('命中预设档用档位标签', () => {
    expect(formatTokens(131072)).toBe('128K');
    expect(formatTokens(524288)).toBe('512K');
    expect(formatTokens(200000)).toBe('200K');
  });

  it('整千/整百千用十进制 K/M, 其余原样', () => {
    expect(formatTokens(512000)).toBe('512K');
    expect(formatTokens(2000000)).toBe('2M');
    expect(formatTokens(51234)).toBe('51234');
  });
});
