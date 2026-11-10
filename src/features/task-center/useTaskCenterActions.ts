// src/features/task-center/useTaskCenterActions.ts
//
// 任务卡片上的动作分发。所有失败都吞掉并 toast —— 与 goalStore / todoStore
// 的错误处理风格一致：任务中心是增强视图，不能因为一次取消失败炸页面。
import { useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { cancelGoal, pauseGoal, startGoal } from '../../entities/autonomous-goals/goalApi';
import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { invoke } from '../../shared/api/desktopInvoke';
import { scheduledClient } from '../../shared/api/scheduledClient';

import { useTaskCenterStore } from './taskCenterStore';
import type { UnifiedTaskEntry } from './unifiedTaskModel';

export interface TaskCenterActions {
  cancel: (entry: UnifiedTaskEntry) => Promise<void>;
  pause: (entry: UnifiedTaskEntry) => Promise<void>;
  resume: (entry: UnifiedTaskEntry) => Promise<void>;
  runNow: (entry: UnifiedTaskEntry) => Promise<void>;
  open: (entry: UnifiedTaskEntry) => void;
  clearFinished: () => void;
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useTaskCenterActions(): TaskCenterActions {
  const navigate = useNavigate();
  const cancelLane = useLaneBoardStore((s) => s.cancel);
  const openShellStream = useTaskCenterStore((s) => s.openShellStream);
  const openDelivery = useTaskCenterStore((s) => s.openDelivery);
  const setHighlight = useTaskCenterStore((s) => s.setHighlight);
  const clearFinished = useTaskCenterStore((s) => s.clearFinished);

  const cancel = useCallback(
    async (entry: UnifiedTaskEntry) => {
      if (!entry.cancellable || !entry.cancelRef) return;
      try {
        const { source, rawId } = entry.cancelRef;
        if (source === 'registry') {
          await invoke('shell_kill', { id: rawId });
        } else if (source === 'chat') {
          const { cancelSessionStream } = await import('../send-message/useChat');
          await cancelSessionStream(rawId);
        } else if (source === 'lane') {
          await cancelLane(rawId);
        } else if (source === 'goal') {
          await cancelGoal(rawId);
        }
      } catch (err) {
        toast.error(toMessage(err));
      }
    },
    [cancelLane],
  );

  const pause = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'goal' || !entry.cancelRef) return;
    try {
      await pauseGoal(entry.cancelRef.rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const resume = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'goal' || !entry.cancelRef) return;
    try {
      await startGoal(entry.cancelRef.rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const runNow = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'scheduled') return;
    const prefix = 'scheduled:';
    const rawId = entry.id.startsWith(prefix) ? entry.id.slice(prefix.length) : '';
    if (!rawId) return;
    try {
      await scheduledClient.runNow(rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const open = useCallback(
    (entry: UnifiedTaskEntry) => {
      // A4 / Phase 5：交付抽屉与 shell 输出抽屉优先于路由跳转
      if (entry.openTarget) {
        const target = entry.openTarget;
        if (target.kind === 'shell') {
          openShellStream(target.shellId);
        } else if (target.kind === 'lane-delivery') {
          openDelivery({ kind: 'lane', laneId: target.laneId });
        } else {
          openDelivery({ kind: 'office', entryId: target.entryId });
        }
        return;
      }
      // P11: office 任务带关联文档名 → 跳转后定位并高亮对应文档行
      if (entry.source === 'registry' && entry.detailPath === '/office' && entry.meta.docName) {
        setHighlight(String(entry.meta.docName));
      }
      if (entry.detailPath) navigate(entry.detailPath);
    },
    [navigate, openShellStream, openDelivery, setHighlight],
  );

  return useMemo(
    () => ({
      cancel,
      pause,
      resume,
      runNow,
      open,
      clearFinished: () => clearFinished(),
    }),
    [cancel, pause, resume, runNow, open, clearFinished],
  );
}
