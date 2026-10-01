import { describe, expect, it } from 'vitest';

import type { Todo } from '../../../shared/api/types';
import {
  aggregateAttention,
  attentionSummary,
  attentionTitle,
  emptyAttentionSnapshot,
  ATTENTION_KINDS,
} from '../index';
import { countDirtyFiles, countPendingTodos } from '../index';

function todo(status: Todo['status']): Todo {
  return {
    id: 1,
    title: 't',
    status,
    priority: 'medium',
    is_recurring: false,
    created_at: '',
    updated_at: '',
  };
}

describe('aggregateAttention', () => {
  it('全零时返回空快照（保持安静）', () => {
    expect(aggregateAttention({})).toEqual({ total: 0, entries: [] });
    expect(emptyAttentionSnapshot().total).toBe(0);
  });

  it('合计所有来源计数', () => {
    const snap = aggregateAttention({
      pendingApprovals: 1,
      pendingQuestions: 1,
      unseenArtifacts: 3,
      pendingTodos: 2,
      dirtyFiles: 4,
    });
    expect(snap.total).toBe(11);
  });

  it('按风险顺序排列条目（审批 > 提问 > 产物 > 待办 > 改动）', () => {
    const snap = aggregateAttention({
      dirtyFiles: 1,
      pendingTodos: 1,
      unseenArtifacts: 1,
      pendingQuestions: 1,
      pendingApprovals: 1,
    });
    expect(snap.entries.map((e) => e.kind)).toEqual([
      'approval',
      'question',
      'artifact',
      'todo',
      'git',
    ]);
  });

  it('只保留 count > 0 的条目', () => {
    const snap = aggregateAttention({ pendingApprovals: 1, pendingTodos: 0, dirtyFiles: 3 });
    expect(snap.entries).toHaveLength(2);
    expect(snap.entries.map((e) => e.kind)).toEqual(['approval', 'git']);
  });

  it('负数 / NaN / Infinity 归零，不污染合计', () => {
    const snap = aggregateAttention({
      pendingApprovals: -3,
      pendingQuestions: Number.NaN,
      unseenArtifacts: Number.POSITIVE_INFINITY,
      pendingTodos: 2,
    });
    expect(snap.total).toBe(2);
    expect(snap.entries.map((e) => e.kind)).toEqual(['todo']);
  });

  it('小数向下取整，避免 1.5 项待处理这种读不出来的总数', () => {
    expect(aggregateAttention({ pendingTodos: 1.9 }).total).toBe(1);
  });

  it('每个 kind 都有中文短标签', () => {
    const snap = aggregateAttention({
      pendingApprovals: 1,
      pendingQuestions: 1,
      unseenArtifacts: 1,
      pendingTodos: 1,
      dirtyFiles: 1,
    });
    expect(snap.entries.map((e) => e.label)).toEqual([
      '待审批',
      '待回答',
      '新产物',
      '待办',
      '未提交改动',
    ]);
  });

  it('刻意不含定时任务：store 无到期判定，不发明语义', () => {
    expect(ATTENTION_KINDS).not.toContain('cron');
    expect(ATTENTION_KINDS).toEqual(['approval', 'question', 'artifact', 'todo', 'git']);
  });
});

describe('attentionTitle / attentionSummary', () => {
  it('title 与 AttnBadge 既有文案口径一致', () => {
    expect(attentionTitle(aggregateAttention({ pendingApprovals: 1 }))).toBe('1 项待处理');
    expect(attentionTitle(aggregateAttention({}))).toBe('无待处理');
  });

  it('summary 逐条展开，空时给出明确文案', () => {
    expect(
      attentionSummary(aggregateAttention({ pendingApprovals: 1, pendingTodos: 3 })),
    ).toBe('待审批 1 · 待办 3');
    expect(attentionSummary(aggregateAttention({}))).toBe('无待处理');
  });
});

describe('countPendingTodos', () => {
  it('pending 与 in_progress 都算待办，completed / cancelled 不算', () => {
    const todos = [
      todo('pending'),
      todo('in_progress'),
      todo('completed'),
      todo('cancelled'),
    ] as Todo[];
    expect(countPendingTodos(todos)).toBe(2);
  });

  it('undefined 安全', () => {
    expect(countPendingTodos(undefined)).toBe(0);
  });
});

describe('countDirtyFiles', () => {
  it('clean 时返回 0，未拉取（undefined）也返回 0', () => {
    expect(countDirtyFiles({ clean: true, changes: [] } as never)).toBe(0);
    expect(countDirtyFiles(undefined)).toBe(0);
  });

  it('不干净时返回涉及文件数', () => {
    const changes = [{ path: 'a.ts' }, { path: 'b.ts' }] as never;
    expect(countDirtyFiles({ clean: false, changes } as never)).toBe(2);
  });
});
