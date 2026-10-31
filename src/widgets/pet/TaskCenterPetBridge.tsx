/**
 * Forwards Task Center entries from the main window to the pet controller.
 *
 * Task Center is renderer-local (office/wiki/custom/orchestration busy states),
 * so the pet main process cannot poll it directly; this bridge reports a
 * compact snapshot whenever the set of non-terminal tasks changes.
 */

import { useEffect, useRef } from 'react';

import { toPetTaskReports } from '../../features/task-center/petReports';
import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';

export function TaskCenterPetBridge(): null {
  const tasks = useTaskCenterStore((state) => state.tasks);
  const lastSent = useRef('');

  useEffect(() => {
    const reports = toPetTaskReports(tasks);
    const key = JSON.stringify(reports);
    if (key === lastSent.current) return;
    lastSent.current = key;
    window.electronAPI?.pet?.reportTasks?.(reports);
  }, [tasks]);

  return null;
}
