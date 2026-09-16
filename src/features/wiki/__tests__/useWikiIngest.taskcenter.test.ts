/**
 * P4 第二切片: useWikiIngest → 任务中心联动。
 * listen 经 desktopEvent 模块；此处 mock 其实现以注入进度事件。
 */
import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

type ProgressPayload = { stage: string; percent: number; message?: string | null };
/** 与真实 preload shim 一致：handler 收到的是事件包装对象 { payload } */
type Handler = (e: { payload: ProgressPayload }) => void;

const handlers = new Map<string, Handler>();
let unlistenCalls = 0;

vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: vi.fn((eventName: string, handler: Handler) => {
    handlers.set(eventName, handler);
    return Promise.resolve(() => {
      unlistenCalls += 1;
    });
  }),
}));

import { useTaskCenterStore } from '../../task-center/taskCenterStore';
import { useWikiIngest } from '../useWikiIngest';

const TASK_ID = 'wiki:ingest:ing-1';

describe('useWikiIngest × taskCenterStore (P4)', () => {
  beforeEach(() => {
    handlers.clear();
    unlistenCalls = 0;
    useTaskCenterStore.setState({ tasks: {} });
  });

  it('进度事件上抬到任务中心，completed 后任务消除', async () => {
    const { result } = renderHook(() => useWikiIngest('ing-1'));
    await waitFor(() => expect(handlers.has('wiki-ingest-ing-1-progress')).toBe(true));

    act(() => {
      handlers.get('wiki-ingest-ing-1-progress')!({ payload: { stage: 'parsing', percent: 10 } });
    });
    expect(useTaskCenterStore.getState().tasks[TASK_ID]?.phase).toBe('parsing');

    act(() => {
      handlers.get('wiki-ingest-ing-1-progress')!({
        payload: { stage: 'completed', percent: 100 },
      });
    });
    await waitFor(() => {
      expect(result.current.done).toBe(true);
    });
    expect(useTaskCenterStore.getState().tasks[TASK_ID]).toBeUndefined();
  });

  it('组件卸载后模块级监听常驻：进度仍上抬任务中心（中途离页不丢任务）', async () => {
    const { unmount } = renderHook(() => useWikiIngest('ing-2'));
    await waitFor(() => expect(handlers.has('wiki-ingest-ing-2-progress')).toBe(true));

    unmount();
    // 模块级监听未拆除：unlistenCalls 保持 0（completed 才拆除）
    expect(unlistenCalls).toBe(0);

    act(() => {
      handlers.get('wiki-ingest-ing-2-progress')!({ payload: { stage: 'embedding', percent: 50 } });
    });
    expect(useTaskCenterStore.getState().tasks['wiki:ingest:ing-2']).toBeDefined();
  });
});

describe('Wiki failure terminal cleanup (audit #6)', () => {
  it.each(['failed', 'cancelled'])(
    'cleans %s subscriptions and reports the error',
    async (stage) => {
      const id = `terminal-${stage}`;
      const { result } = renderHook(() => useWikiIngest(id));
      await waitFor(() => expect(handlers.has(`wiki-ingest-${id}-progress`)).toBe(true));
      // Wait for asynchronous unlisten registration before delivering the terminal.
      await act(async () => {});
      const before = unlistenCalls;
      act(() =>
        handlers.get(`wiki-ingest-${id}-progress`)!({
          payload: { stage, percent: 0, message: 'network down' },
        }),
      );
      expect(result.current.error).toBe('network down');
      expect(useTaskCenterStore.getState().tasks[`wiki:ingest:${id}`]).toBeUndefined();
      expect(unlistenCalls).toBe(before + 1);
    },
  );
});
