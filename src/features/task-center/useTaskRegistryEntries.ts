// src/features/task-center/useTaskRegistryEntries.ts
//
// 将 taskCenterStore 的 registry 条目归一化为 UnifiedTaskEntry[]。
// 侧边栏 TaskCenterPanel 与 /tasks 页面共用此 hook 获取 registry 段。
import { useMemo } from 'react';

import { useTaskCenterStore } from './taskCenterStore';
import { normalizeRegistryTask } from './unifiedTaskModel';
import type { UnifiedTaskEntry } from './unifiedTaskModel';

export function useTaskRegistryEntries(): UnifiedTaskEntry[] {
  const tasks = useTaskCenterStore((s) => s.tasks);
  return useMemo(() => Object.values(tasks).map(normalizeRegistryTask), [tasks]);
}
