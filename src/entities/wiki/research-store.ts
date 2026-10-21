// Research Store - 深度研究状态管理
import { create } from 'zustand';

import type { ResearchTask, WebResult } from '../../shared/types/wiki';

interface ResearchStoreState {
  tasks: ResearchTask[];
  panelOpen: boolean;
  maxConcurrent: number;

  setTasks: (tasks: ResearchTask[]) => void;
  addTask: (task: ResearchTask) => void;
  updateTask: (id: string, patch: Partial<ResearchTask>) => void;
  removeTask: (id: string) => void;
  appendSynthesis: (id: string, chunk: string) => void;
  addWebResult: (id: string, result: WebResult) => void;
  setPanelOpen: (open: boolean) => void;
}

export const useResearchStore = create<ResearchStoreState>((set) => ({
  tasks: [],
  panelOpen: false,
  maxConcurrent: 3,

  setTasks: (tasks) => set({ tasks }),
  addTask: (task) => set((state) => ({ tasks: [...state.tasks, task] })),
  updateTask: (id, patch) =>
    set((state) => ({
      tasks: state.tasks.map((task) => (task.id === id ? { ...task, ...patch } : task)),
    })),
  removeTask: (id) => set((state) => ({ tasks: state.tasks.filter((t) => t.id !== id) })),
  appendSynthesis: (id, chunk) =>
    set((state) => ({
      tasks: state.tasks.map((task) =>
        task.id === id ? { ...task, synthesis: task.synthesis + chunk } : task,
      ),
    })),
  addWebResult: (id, result) =>
    set((state) => ({
      tasks: state.tasks.map((task) =>
        task.id === id ? { ...task, webResults: [...task.webResults, result] } : task,
      ),
    })),
  setPanelOpen: (open) => set({ panelOpen: open }),
}));

/* v8 ignore start */
export function formatResearchStoreSummary(
  tasks: ResearchTask[] = [],
  panelOpen = false,
  maxConcurrent = 3,
): string {
  const doneCount = tasks.filter((t) => t.status === 'done').length;
  return `tasks=${tasks.length} · done=${doneCount} · maxConcurrent=${maxConcurrent} · panel=${panelOpen ? 'open' : 'closed'}`;
}

export function formatResearchStoreJson(
  tasks: ResearchTask[] = [],
  panelOpen = false,
  maxConcurrent = 3,
): string {
  return JSON.stringify({
    taskCount: tasks.length,
    doneCount: tasks.filter((t) => t.status === 'done').length,
    panelOpen,
    maxConcurrent,
  });
}
/* v8 ignore stop */
