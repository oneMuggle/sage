/**
 * IPC client for scheduled tasks (Phase 8).
 *
 * Translates to backend HTTP via Electron preload:
 *   scheduled_list_tasks   → GET    /api/v1/scheduled/tasks
 *   scheduled_create_task  → POST   /api/v1/scheduled/tasks
 *   scheduled_update_task  → PATCH  /api/v1/scheduled/tasks/{id}
 *   scheduled_delete_task  → DELETE /api/v1/scheduled/tasks/{id}
 *   scheduled_run_task     → POST   /api/v1/scheduled/tasks/{id}/run
 *
 * All methods throw on IPC failure; callers should wrap in try/catch and
 * surface a toast on failure.
 */
import { invoke } from './desktopInvoke';
import type { CreateTaskInput, ScheduledTask, UpdateTaskInput } from './types';

export const scheduledClient = {
  async list(): Promise<ScheduledTask[]> {
    return invoke<ScheduledTask[]>('scheduled_list_tasks', {});
  },

  async create(input: CreateTaskInput): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_create_task', { input });
  },

  async update(id: string, changes: UpdateTaskInput): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_update_task', { id, changes });
  },

  async delete(id: string): Promise<void> {
    await invoke<void>('scheduled_delete_task', { id });
  },

  async runNow(id: string): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_run_task', { id });
  },
};
