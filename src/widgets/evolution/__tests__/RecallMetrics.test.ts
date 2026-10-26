// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';

import type { RecentRecallEvent, RecallVariantBucket } from '../RecallMetrics';
import { compareVariants, findVariantWeights } from '../RecallMetrics';

const makeBucket = (overrides: Partial<RecallVariantBucket> = {}): RecallVariantBucket => ({
  total: 0,
  feedback_count: 0,
  positive_count: 0,
  negative_count: 0,
  satisfaction_rate: 0,
  feedback_satisfaction_rate: 0,
  avg_result_count: 0,
  ...overrides,
});

const makeEvent = (overrides: Partial<RecentRecallEvent> = {}): RecentRecallEvent => ({
  id: 'id-1',
  query_hash: 'd4e5f6a7',
  session_id: null,
  variant: null,
  weights_json: null,
  result_count: null,
  user_feedback: null,
  created_at: 1730123456,
  ...overrides,
});

describe('compareVariants (P0-3 A/B 对比结论)', () => {
  it('reports "只有一个变体有数据" when fewer than 2 variants exist', () => {
    const result = compareVariants({ A: makeBucket({ total: 10 }) });
    expect(result.leader).toBeNull();
    expect(result.reason).toBe('只有一个变体有数据，暂无对比');
  });

  it('reports "反馈量不足" when either side has <5 feedback', () => {
    const result = compareVariants({
      A: makeBucket({ feedback_count: 10, feedback_satisfaction_rate: 0.9 }),
      B: makeBucket({ feedback_count: 3, feedback_satisfaction_rate: 0.3 }),
    });
    expect(result.leader).toBeNull();
    expect(result.reason).toContain('反馈量不足');
  });

  it('declares A the leader when A has higher feedback_satisfaction_rate', () => {
    const result = compareVariants({
      A: makeBucket({ feedback_count: 10, feedback_satisfaction_rate: 0.9 }),
      B: makeBucket({ feedback_count: 8, feedback_satisfaction_rate: 0.5 }),
    });
    expect(result.leader).toBe('A');
    expect(result.margin).toBeCloseTo(0.4, 4);
    expect(result.reason).toContain('变体 A');
    expect(result.reason).toContain('40.0');
  });

  it('declares B the leader when B has higher feedback_satisfaction_rate', () => {
    const result = compareVariants({
      A: makeBucket({ feedback_count: 10, feedback_satisfaction_rate: 0.3 }),
      B: makeBucket({ feedback_count: 12, feedback_satisfaction_rate: 0.75 }),
    });
    expect(result.leader).toBe('B');
    expect(result.margin).toBeCloseTo(0.45, 4);
  });

  it('returns null leader when both variants are tied', () => {
    const result = compareVariants({
      A: makeBucket({ feedback_count: 6, feedback_satisfaction_rate: 0.5 }),
      B: makeBucket({ feedback_count: 6, feedback_satisfaction_rate: 0.5 }),
    });
    expect(result.leader).toBeNull();
    expect(result.reason).toContain('持平');
  });

  it('handles empty by_variant map', () => {
    const result = compareVariants({});
    expect(result.leader).toBeNull();
    expect(result.variantA).toBeNull();
    expect(result.variantB).toBeNull();
    expect(result.reason).toBe('只有一个变体有数据，暂无对比');
  });

  it('sorts variant names so comparison is deterministic', () => {
    // by_variant 的键顺序来自 SQL GROUP BY，不保证；前端必须按字母序定位 A/B。
    const result = compareVariants({
      B: makeBucket({ feedback_count: 10, feedback_satisfaction_rate: 0.9 }),
      A: makeBucket({ feedback_count: 10, feedback_satisfaction_rate: 0.4 }),
    });
    expect(result.variantA).toBe('A');
    expect(result.variantB).toBe('B');
    expect(result.leader).toBe('B');
  });
});

describe('findVariantWeights (P0-3 反查融合权重)', () => {
  it('returns weights_json from the first recent event matching the variant', () => {
    const recent = [
      makeEvent({ id: 'r1', variant: 'B', weights_json: '[0.5, 0.5]' }),
      makeEvent({ id: 'r2', variant: 'A', weights_json: '[0.2, 0.8]' }),
      makeEvent({ id: 'r3', variant: 'A', weights_json: '[0.2, 0.8]' }),
    ];
    expect(findVariantWeights(recent, 'A')).toBe('[0.2, 0.8]');
    expect(findVariantWeights(recent, 'B')).toBe('[0.5, 0.5]');
  });

  it('returns null when variant is absent or has no weights_json', () => {
    const recent = [
      makeEvent({ id: 'r1', variant: 'A', weights_json: null }),
      makeEvent({ id: 'r2', variant: null, weights_json: '[0.5, 0.5]' }),
    ];
    expect(findVariantWeights(recent, 'C')).toBeNull();
    // A 有事件但 weights_json 为空 —— 必须 null，不能泄漏其它变体的权重
    expect(findVariantWeights(recent, 'A')).toBeNull();
  });

  it('skips events with null variant even when weights exist', () => {
    const recent = [makeEvent({ variant: null, weights_json: '[0.5, 0.5]' })];
    expect(findVariantWeights(recent, 'A')).toBeNull();
  });

  it('returns null for empty recent list', () => {
    expect(findVariantWeights([], 'A')).toBeNull();
  });
});
