// src/features/task-center/TaskCenterRuntimeHost.tsx
//
// 常驻轮询宿主 —— 挂在 Layout，永不受侧边栏折叠影响。
// 为什么不在分区里轮询：SiderSection 折叠后 render() 不再调用，
// 后台 shell 退出将永远反映不到任务中心（spec §5.4）。
import { useEffect } from 'react';

import { listShells } from '../../shared/api/shellApi';

import { useTaskCenterStore } from './taskCenterStore';
import { useUnifiedTaskStore } from './unifiedTaskStore';

const SHELL_TASK_POLL_MS = 3_000;
const GOAL_POLL_MS = 10_000;
const SLOW_SOURCE_POLL_MS = 30_000;

const NON_TERMINAL_GOAL = new Set(['pending', 'running', 'paused']);

export function TaskCenterRuntimeHost(): null {
  const registerShell = useTaskCenterStore((s) => s.registerShell);
  const removeMissingShells = useTaskCenterStore((s) => s.removeMissingShells);

  // shell 3s 轮询（沿用旧胶囊的同 cadence 轮询：列出现存 shell、注册新条目、清除已消失条目）
  useEffect(() => {
    let cancelled = false;
    const poll = (): void => {
      listShells()
        .then((shells) => {
          if (cancelled) return;
          for (const shell of shells) {
            registerShell({
              shell_id: shell.shell_id,
              command: shell.command,
              status: shell.status,
              exit_code: shell.exit_code ?? null,
              age_seconds: shell.age_seconds,
            });
          }
          removeMissingShells(shells.map((s) => s.shell_id));
        })
        .catch(() => {
          /* 静默：任务中心是增强信息 */
        });
    };
    poll();
    const timer = window.setInterval(poll, SHELL_TASK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [registerShell, removeMissingShells]);

  // goal 10s 轮询，仅在存在非终态目标时继续
  useEffect(() => {
    const timer = window.setInterval(() => {
      const { goals, refreshGoals } = useUnifiedTaskStore.getState();
      if (goals.some((g) => NON_TERMINAL_GOAL.has(g.status))) void refreshGoals();
    }, GOAL_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  // todo / scheduled 30s 轮询，仅在存在活动条目时继续
  useEffect(() => {
    const timer = window.setInterval(() => {
      const { todos, scheduledTasks, refreshTodos, refreshScheduled } =
        useUnifiedTaskStore.getState();
      if (todos.some((t) => t.status === 'in_progress')) void refreshTodos();
      if (scheduledTasks.some((t) => t.last_status === 'running')) void refreshScheduled();
    }, SLOW_SOURCE_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  // 首屏拉一次三源（不等轮询）
  useEffect(() => {
    void useUnifiedTaskStore.getState().refresh();
  }, []);

  return null;
}
