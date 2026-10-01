import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { useTodoStore } from '../../../entities/todo/todoStore';
import type { Todo } from '../../../shared/api/types';
import { useChangesListStore } from '../../changes/changesListStore';
import { useAttentionSnapshot } from '../index';

const PENDING_PERMISSION = {
  request_id: 'req-1',
  tool_name: 'terminal',
  args_summary: '{}',
  risk: 'suspicious' as const,
  message: '需要执行终端命令',
  created_at: 0,
};

function todo(status: Todo['status']): Todo {
  return {
    id: Math.random(),
    title: 't',
    status,
    priority: 'medium',
    is_recurring: false,
    created_at: '',
    updated_at: '',
  };
}

beforeEach(() => {
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  useTodoStore.setState({ todos: [] });
  useChangesListStore.setState({ bySession: {} });
});

describe('useAttentionSnapshot', () => {
  it('无任何来源时返回空快照', () => {
    const { result } = renderHook(() => useAttentionSnapshot());
    expect(result.current.total).toBe(0);
    expect(result.current.entries).toEqual([]);
  });

  it('审批挂起时计入总数', () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    const { result } = renderHook(() => useAttentionSnapshot());
    expect(result.current.total).toBe(1);
    expect(result.current.entries[0].kind).toBe('approval');
  });

  it('待办按 pending / in_progress 计入', () => {
    useTodoStore.setState({ todos: [todo('pending'), todo('in_progress'), todo('completed')] });
    const { result } = renderHook(() => useAttentionSnapshot());
    expect(result.current.total).toBe(2);
    expect(result.current.entries.map((e) => e.kind)).toEqual(['todo']);
  });

  it('变更按会话取：只统计传入 sessionId 的工作区', () => {
    useChangesListStore.setState({
      bySession: {
        s1: { clean: false, changes: [{ path: 'a.ts' }, { path: 'b.ts' }] },
        s2: { clean: true, changes: [] },
      } as never,
    });

    const { result } = renderHook(() => useAttentionSnapshot({ sessionId: 's1' }));
    expect(result.current.total).toBe(2);

    const clean = renderHook(() => useAttentionSnapshot({ sessionId: 's2' }));
    expect(clean.result.current.total).toBe(0);

    const none = renderHook(() => useAttentionSnapshot({ sessionId: null }));
    expect(none.result.current.total).toBe(0);
  });

  it('未读产物由调用方传入（判定依赖 rightPanelStore 的已见基线）', () => {
    const { result } = renderHook(() => useAttentionSnapshot({ unseenArtifacts: 4 }));
    expect(result.current.total).toBe(4);
    expect(result.current.entries[0].kind).toBe('artifact');
  });

  it('多来源合计并按风险排序', () => {
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    useTodoStore.setState({ todos: [todo('pending')] });
    const { result } = renderHook(() =>
      useAttentionSnapshot({ unseenArtifacts: 2, sessionId: null }),
    );
    expect(result.current.total).toBe(4);
    expect(result.current.entries.map((e) => e.kind)).toEqual(['approval', 'artifact', 'todo']);
  });

  it('来源不变时返回稳定引用（避免下游无谓重渲染）', () => {
    const { result, rerender } = renderHook(() => useAttentionSnapshot());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
