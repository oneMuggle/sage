import { describe, expect, it } from 'vitest';

import { parseQuickTodo } from '../parseQuickTodo';

// 固定时钟：2026-01-14（周三）10:00 本地时间，保证日期计算确定性。
const NOW = new Date(2026, 0, 14, 10, 0, 0);

describe('parseQuickTodo', () => {
  it('returns the plain title when nothing parses', () => {
    const result = parseQuickTodo('交周报', NOW);
    expect(result.title).toBe('交周报');
    expect(result.dueAt).toBeUndefined();
    expect(result.priority).toBeUndefined();
    expect(result.tags).toEqual([]);
  });

  it('parses 明天 + 下午3点', () => {
    const result = parseQuickTodo('明天下午3点交报告', NOW);
    expect(result.title).toBe('交报告');
    expect(result.dueAt).toBe('2026-01-15T15:00:00');
  });

  it('parses 后天 + 9点半', () => {
    const result = parseQuickTodo('后天 9点半 开会', NOW);
    expect(result.title).toBe('开会');
    expect(result.dueAt).toBe('2026-01-16T09:30:00');
  });

  it('parses 周一 as the next Monday', () => {
    const result = parseQuickTodo('周一 9:00 站会', NOW);
    expect(result.title).toBe('站会');
    expect(result.dueAt).toBe('2026-01-19T09:00:00');
  });

  it('parses 下周三 as next calendar week', () => {
    const result = parseQuickTodo('下周三 9点 复盘', NOW);
    expect(result.title).toBe('复盘');
    expect(result.dueAt).toBe('2026-01-21T09:00:00');
  });

  it('parses 本周一 as this week (may be in the past)', () => {
    const result = parseQuickTodo('本周一 10点 补交', NOW);
    expect(result.dueAt).toBe('2026-01-12T10:00:00');
  });

  it('parses 大后天 with the default 18:00 due time', () => {
    const result = parseQuickTodo('大后天 体检', NOW);
    expect(result.title).toBe('体检');
    expect(result.dueAt).toBe('2026-01-17T18:00:00');
  });

  it('parses 1月20日 with explicit time', () => {
    const result = parseQuickTodo('1月20日 18:00 答辩', NOW);
    expect(result.title).toBe('答辩');
    expect(result.dueAt).toBe('2026-01-20T18:00:00');
  });

  it('rolls a past month-day to next year', () => {
    const result = parseQuickTodo('1月2日 交材料', NOW);
    expect(result.dueAt).toBe('2027-01-02T18:00:00');
  });

  it('parses multiple tags and Chinese priority', () => {
    const result = parseQuickTodo('写论文 !高 #工作 #论文', NOW);
    expect(result.title).toBe('写论文');
    expect(result.priority).toBe('high');
    expect(result.tags).toEqual(['工作', '论文']);
  });

  it('accepts English priority tokens', () => {
    const result = parseQuickTodo('整理照片 !low', NOW);
    expect(result.title).toBe('整理照片');
    expect(result.priority).toBe('low');
  });

  it('rolls a past time-only entry to tomorrow', () => {
    const result = parseQuickTodo('9点 喝水', NOW);
    expect(result.dueAt).toBe('2026-01-15T09:00:00');
  });

  it('keeps a future time-only entry today', () => {
    const result = parseQuickTodo('23点 睡觉', NOW);
    expect(result.dueAt).toBe('2026-01-14T23:00:00');
  });

  it('maps 晚上 to PM hours', () => {
    const result = parseQuickTodo('晚上8点 跑步', NOW);
    expect(result.dueAt).toBe('2026-01-14T20:00:00');
  });

  it('dedupes repeated tags', () => {
    const result = parseQuickTodo('任务 #a #a #b', NOW);
    expect(result.tags).toEqual(['a', 'b']);
  });

  it('falls back to the original input when only tokens were typed', () => {
    const result = parseQuickTodo('#无标题', NOW);
    expect(result.tags).toEqual(['无标题']);
    expect(result.title).toBe('#无标题');
  });
});
