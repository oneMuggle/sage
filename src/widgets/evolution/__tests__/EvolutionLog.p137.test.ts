import { describe, expect, it } from 'vitest';

import { evaluateEvolutionLogGovernanceAudit, parseEvolutionMetrics } from '../EvolutionLog';

describe('evaluateEvolutionLogGovernanceAudit (Phase P137)', () => {
  it('returns healthy report for valid page size, low failure rate, and responsive loading', () => {
    const report = evaluateEvolutionLogGovernanceAudit({
      entryCount: 20,
      pageSize: 20,
      failedEntryCount: 1,
      loadingStuckMs: 250,
    });
    expect(report.healthy).toBe(true);
    expect(report.failureRate).toBe(0.05);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags invalid page size, high failure rate, and stuck loading state', () => {
    const report = evaluateEvolutionLogGovernanceAudit({
      entryCount: 10,
      pageSize: 0,
      failedEntryCount: 8,
      loadingStuckMs: 25000,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'EVOLUTION_LOG_PAGE_SIZE_INVALID',
      'EVOLUTION_LOG_HIGH_FAILURE_RATE',
      'EVOLUTION_LOG_LOADING_STUCK',
    ]);
  });
});

describe('parseEvolutionMetrics (P0-1)', () => {
  it('returns empty array for null / undefined / empty string', () => {
    expect(parseEvolutionMetrics(null)).toEqual([]);
    expect(parseEvolutionMetrics(undefined)).toEqual([]);
    expect(parseEvolutionMetrics('')).toEqual([]);
  });

  it('returns empty array for invalid JSON (no throw)', () => {
    expect(parseEvolutionMetrics('{not-json')).toEqual([]);
    expect(parseEvolutionMetrics('undefined')).toEqual([]);
  });

  it('returns empty array when parsed value is not a plain object', () => {
    // Arrays / primitives serialize to JSON but aren't key/value metrics.
    expect(parseEvolutionMetrics('[]')).toEqual([]);
    expect(parseEvolutionMetrics('"string-value"')).toEqual([]);
    expect(parseEvolutionMetrics('42')).toEqual([]);
    expect(parseEvolutionMetrics('null')).toEqual([]);
  });

  it('stringifies non-string values; passes strings through verbatim', () => {
    const input = JSON.stringify({
      scanned: 128,
      merged: 3,
      status: 'success',
      tags: ['a', 'b'],
    });
    expect(parseEvolutionMetrics(input)).toEqual([
      ['scanned', '128'],
      ['merged', '3'],
      ['status', 'success'],
      ['tags', '["a","b"]'],
    ]);
  });

  it('handles metrics with Chinese characters (ensure_ascii=False 写入路径)', () => {
    // 后端 json.dumps(..., ensure_ascii=False)，因此 metrics_json 里
    // 可能有中文。前端 JSON.parse 原生支持。
    const input = JSON.stringify({ description: '已合并 3 条重复偏好' });
    expect(parseEvolutionMetrics(input)).toEqual([['description', '已合并 3 条重复偏好']]);
  });
});
