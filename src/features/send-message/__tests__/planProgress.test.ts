import { describe, expect, it } from 'vitest';

import { agentStateToPhase, agentStateToText } from '../../../shared/lib/agentStateMapping';
import { isPlanningActive, reducePlanProgress, type PlanStageState } from '../planProgress';
import type { PlanProgressItem } from '../../../shared/api/types/chatAndEventTypes';

function item(over: Partial<PlanProgressItem> = {}): PlanProgressItem {
  return {
    stage: 'scout',
    status: 'progress',
    kind: 'message',
    text: '',
    ...over,
  };
}

describe('plan_progress state 映射', () => {
  it('不进占位文本、不产生阶段指示', () => {
    expect(agentStateToText('plan_progress')).toBeNull();
    expect(agentStateToPhase('plan_progress')).toBeNull();
  });
});

describe('reducePlanProgress', () => {
  it('首次事件创建阶段并置为 started', () => {
    const out = reducePlanProgress(null, item({ status: 'started' }));
    expect(out).toHaveLength(1);
    expect(out[0].stage).toBe('scout');
    expect(out[0].status).toBe('started');
  });

  it('追加非心跳文本行', () => {
    const first = reducePlanProgress(null, item({ kind: 'thinking', text: 'a' }));
    const second = reducePlanProgress(first, item({ kind: 'tool_call', text: 'b' }));
    expect(second[0].lines.map((l) => l.text)).toEqual(['a', 'b']);
  });

  it('心跳不追加文本行但更新耗时', () => {
    const first = reducePlanProgress(null, item({ kind: 'message', text: 'a' }));
    const second = reducePlanProgress(
      first,
      item({ kind: 'heartbeat', status: 'progress', elapsed_ms: 5000 }),
    );
    expect(second[0].lines.map((l) => l.text)).toEqual(['a']);
    expect(second[0].elapsedMs).toBe(5000);
  });

  it('重复文本不重复追加', () => {
    const first = reducePlanProgress(null, item({ kind: 'thinking', text: 'same' }));
    const second = reducePlanProgress(first, item({ kind: 'thinking', text: 'same' }));
    expect(second[0].lines).toHaveLength(1);
  });

  it('按阶段顺序排序', () => {
    let stages: PlanStageState[] | null = null;
    stages = reducePlanProgress(stages, item({ stage: 'decompose', status: 'started' }));
    stages = reducePlanProgress(stages, item({ stage: 'complexity_classify', status: 'started' }));
    expect(stages.map((s) => s.stage)).toEqual(['complexity_classify', 'decompose']);
  });

  it('终态更新 status', () => {
    const first = reducePlanProgress(null, item({ status: 'started' }));
    const done = reducePlanProgress(first, item({ status: 'done', text: 'ok' }));
    expect(done[0].status).toBe('done');
    expect(done[0].lines.at(-1)?.text).toBe('ok');
  });

  it('单阶段最多保留 20 行', () => {
    let stages: PlanStageState[] | null = null;
    for (let i = 0; i < 30; i += 1) {
      stages = reducePlanProgress(stages, item({ kind: 'message', text: `line-${i}` }));
    }
    expect(stages?.[0].lines).toHaveLength(20);
    expect(stages?.[0].lines.at(-1)?.text).toBe('line-29');
  });

  it('超长文本截断到 240 字符', () => {
    const out = reducePlanProgress(null, item({ kind: 'message', text: 'x'.repeat(400) }));
    expect(out[0].lines[0].text).toHaveLength(241); // 240 + 省略号
  });
});

describe('isPlanningActive', () => {
  it('有 started/progress 时为真', () => {
    expect(isPlanningActive([{ stage: 'scout', status: 'started', lines: [] }])).toBe(true);
    expect(isPlanningActive([{ stage: 'scout', status: 'done', lines: [] }])).toBe(false);
    expect(isPlanningActive(null)).toBe(false);
  });
});
