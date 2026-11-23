// src/features/orch-notify/__tests__/orchNotify.test.ts
// M4.3a: 编排通知点击 → 任务中心深链（无桥降级 + 定位写入）。
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOrchestrationFocusStore } from '../../../entities/orchestration/orchestrationFocusStore';
import { useRightPanelStore } from '../../right-panel/rightPanelStore';
import { focusOrchThread, onOrchNotifyClick } from '../orchNotify';

// 两个 store 都是进程级单例，用例间会串味。
beforeEach(() => {
  useOrchestrationFocusStore.setState({ request: null });
  useRightPanelStore.setState({ open: false });
});

describe('onOrchNotifyClick', () => {
  it('无 electron 桥时静默 no-op 不抛错', () => {
    const original = window.electronAPI;
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      get: () => undefined,
    });
    try {
      expect(() => onOrchNotifyClick(() => undefined)).not.toThrow();
      expect(onOrchNotifyClick(() => undefined)).toBeUndefined();
    } finally {
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        get: () => original,
      });
    }
  });

  it('有桥时注册监听并把载荷交给回调', async () => {
    const original = window.electronAPI;
    const listen = vi.fn().mockResolvedValue(() => undefined);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      get: () => ({ listen }),
    });
    try {
      const handler = vi.fn();
      await onOrchNotifyClick(handler);
      expect(listen).toHaveBeenCalledWith('orch-notify-click', expect.any(Function), undefined);
      const cb = listen.mock.calls[0][1] as (payload: unknown) => void;
      cb({ sessionId: 's-1', runId: 'orch-1', taskId: 'task-3' });
      expect(handler).toHaveBeenCalledWith({
        sessionId: 's-1',
        runId: 'orch-1',
        taskId: 'task-3',
      });
    } finally {
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        get: () => original,
      });
    }
  });
});

describe('focusOrchThread', () => {
  it('写入编排定位请求并展开右侧 progress 面板', () => {
    const ok = focusOrchThread({
      sessionId: 's-42',
      runId: 'orch-1',
      taskId: 'task-7',
    });
    expect(ok).toBe(true);
    expect(useOrchestrationFocusStore.getState().request).toEqual({
      sessionId: 's-42',
      runId: 'orch-1',
      taskId: 'task-7',
    });
    expect(useRightPanelStore.getState().tab).toBe('progress');
    expect(useRightPanelStore.getState().open).toBe(true);
  });

  it('缺 runId 时不产生定位请求', () => {
    const ok = focusOrchThread({ sessionId: 's-42', runId: '', taskId: '' });
    expect(ok).toBe(false);
    expect(useOrchestrationFocusStore.getState().request).toBeNull();
  });
});
