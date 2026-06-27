import { create } from 'zustand';

import { scheduledClient } from '../../shared/api/scheduledClient';
import type { CreateTaskInput, ScheduledTask, UpdateTaskInput } from '../../shared/api/types';

interface ScheduledTaskState {
  tasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  create: (input: CreateTaskInput) => Promise<ScheduledTask>;
  update: (id: string, changes: UpdateTaskInput) => Promise<ScheduledTask>;
  delete: (id: string) => Promise<void>;
  runNow: (id: string) => Promise<ScheduledTask>;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const useScheduledTaskStore = create<ScheduledTaskState>((set, get) => ({
  tasks: [],
  loading: false,
  error: null,

  async load() {
    set({ loading: true, error: null });
    try {
      const tasks = await scheduledClient.list();
      set({ tasks, loading: false });
    } catch (error: unknown) {
      set({ tasks: [], loading: false, error: getErrorMessage(error) });
    }
  },

  async create(input: CreateTaskInput) {
    const task = await scheduledClient.create(input);
    set({ tasks: [...get().tasks, task] });
    return task;
  },

  async update(id: string, changes: UpdateTaskInput) {
    const updated = await scheduledClient.update(id, changes);
    set({
      tasks: get().tasks.map((t) => (t.id === id ? updated : t)),
    });
    return updated;
  },

  async delete(id: string) {
    try {
      await scheduledClient.delete(id);
      set({ tasks: get().tasks.filter((t) => t.id !== id), error: null });
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      throw error;
    }
  },

  async runNow(id: string) {
    const updated = await scheduledClient.runNow(id);
    set({
      tasks: get().tasks.map((t) => (t.id === id ? updated : t)),
    });
    return updated;
  },
}));
