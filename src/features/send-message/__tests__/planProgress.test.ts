import { describe, expect, it } from 'vitest';

import type { PlanProgressItem } from '../../../shared/api/types/chatAndEventTypes';
import { agentStateToPhase, agentStateToText } from '../../../shared/lib/agentStateMapping';
import { isPlanningActive, reducePlanProgress, type PlanStageState } from '../planProgress';

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

  it('单阶段最多保留 20 行（非 scout）', () => {
    let stages: PlanStageState[] | null = null;
    for (let i = 0; i < 30; i += 1) {
      stages = reducePlanProgress(
        stages,
        item({ stage: 'clarify', kind: 'message', text: `line-${i}` }),
      );
    }
    expect(stages?.[0].lines).toHaveLength(20);
    expect(stages?.[0].lines.at(-1)?.text).toBe('line-29');
  });

  it('超长文本截断到 240 字符（非 scout）', () => {
    const out = reducePlanProgress(
      null,
      item({ stage: 'clarify', kind: 'message', text: 'x'.repeat(400) }),
    );
    expect(out[0].lines[0].text).toHaveLength(241); // 240 + 省略号
  });

  it('scout 阶段放宽到 60 行 / 500 字符', () => {
    let stages: PlanStageState[] | null = null;
    for (let i = 0; i < 80; i += 1) {
      stages = reducePlanProgress(stages, item({ kind: 'message', text: `line-${i}` }));
    }
    expect(stages?.[0].lines).toHaveLength(60);
    expect(stages?.[0].lines.at(-1)?.text).toBe('line-79');

    const long = reducePlanProgress(null, item({ kind: 'message', text: 'x'.repeat(900) }));
    expect(long[0].lines[0].text).toHaveLength(501); // 500 + 省略号
  });
});

describe('reducePlanProgress · 事实清单', () => {
  it('scout done 事件解析 detail.facts', () => {
    const out = reducePlanProgress(
      null,
      item({
        status: 'done',
        detail: {
          facts: [
            { text: '事实甲在这里', source: '文档 A' },
            { text: '事实乙在这里', source: '' },
          ],
          fact_count: 2,
          truncated: false,
        },
      }),
    );
    expect(out[0].facts).toEqual([
      { text: '事实甲在这里', source: '文档 A' },
      { text: '事实乙在这里', source: '' },
    ]);
    expect(out[0].factsTruncated).toBe(false);
  });

  it('非法项丢弃：非对象 / text 非字符串 / 空串', () => {
    const out = reducePlanProgress(
      null,
      item({
        status: 'done',
        detail: {
          facts: [
            { text: '有效事实', source: 'X' },
            null,
            'not-an-object',
            { source: '无正文' },
            { text: 123 },
            { text: '   ' },
          ],
        },
      }),
    );
    expect(out[0].facts).toEqual([{ text: '有效事实', source: 'X' }]);
  });

  it('source 缺失视为空串；正文不截断（4000 字上限内完整保留）', () => {
    // 4000 = 后端 SCOUT_FACT_MAX_CHARS = 上游 raw 上限 —— 合法载荷的最大长度。
    const long = '事'.repeat(4000);
    const out = reducePlanProgress(
      null,
      item({ status: 'done', detail: { facts: [{ text: long }] } }),
    );
    expect(out[0].facts?.[0].source).toBe('');
    expect(out[0].facts?.[0].text).toHaveLength(4000);
  });

  it('超过 4000 字的畸形载荷在防御性上限处截断（正常不会触发）', () => {
    const out = reducePlanProgress(
      null,
      item({ status: 'done', detail: { facts: [{ text: '事'.repeat(5000) }] } }),
    );
    const text = out[0].facts?.[0].text ?? '';
    expect(text).toHaveLength(4001); // 4000 字 + 省略号
    expect(text.endsWith('…')).toBe(true);
  });

  it('detail 非数组 → 不产出 facts', () => {
    const out = reducePlanProgress(
      null,
      item({ status: 'done', detail: { facts: 'not-a-list' } }),
    );
    expect(out[0].facts).toBeUndefined();
  });

  it('非 scout 阶段忽略 detail.facts', () => {
    const out = reducePlanProgress(
      null,
      item({
        stage: 'scout_deep',
        status: 'done',
        detail: { facts: [{ text: '不该出现', source: '' }] },
      }),
    );
    expect(out[0].facts).toBeUndefined();
  });

  it('后端截断标记透传', () => {
    const out = reducePlanProgress(
      null,
      item({
        status: 'done',
        detail: { facts: [{ text: '事实', source: '' }], truncated: true },
      }),
    );
    expect(out[0].factsTruncated).toBe(true);
  });

  it('truncated 标记单调：后续事件缺字段时不得回退为 false', () => {
    const first = reducePlanProgress(
      null,
      item({
        status: 'done',
        detail: { facts: [{ text: '事实甲', source: '' }], truncated: true },
      }),
    );
    expect(first[0].factsTruncated).toBe(true);
    const second = reducePlanProgress(
      first,
      item({
        status: 'done',
        detail: { facts: [{ text: '事实乙', source: '' }] },
      }),
    );
    expect(second[0].factsTruncated).toBe(true);
  });

  it('事实清单在后续事件中保留', () => {
    const first = reducePlanProgress(
      null,
      item({ status: 'done', detail: { facts: [{ text: '事实甲', source: '' }] } }),
    );
    const second = reducePlanProgress(first, item({ status: 'done', text: 'ok' }));
    expect(second[0].facts).toEqual([{ text: '事实甲', source: '' }]);
  });
});

describe('isPlanningActive', () => {
  it('有 started/progress 时为真', () => {
    expect(isPlanningActive([{ stage: 'scout', status: 'started', lines: [] }])).toBe(true);
    expect(isPlanningActive([{ stage: 'scout', status: 'done', lines: [] }])).toBe(false);
    expect(isPlanningActive(null)).toBe(false);
  });
});
