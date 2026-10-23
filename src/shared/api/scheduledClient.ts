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

export function formatScheduledTaskSummary(
  task: Pick<ScheduledTask, 'id' | 'name' | 'type' | 'enabled'>,
): string {
  return `${task.id} · ${task.name} · ${task.type} · ${task.enabled ? 'enabled' : 'disabled'}`;
}

export function formatScheduledTaskJson(
  task: Pick<ScheduledTask, 'id' | 'name' | 'type' | 'enabled' | 'session_id'>,
): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.scheduled_task.v1',
      id: task.id,
      name: task.name,
      type: task.type,
      enabled: task.enabled,
      sessionId: task.session_id ?? null,
    },
    null,
    2,
  );
}

export function auditScheduledClientGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.api.scheduled_client.governance.v1',
      phase: 'P177',
      methods: ['list', 'create', 'update', 'delete', 'runNow'],
      sampleSummary: formatScheduledTaskSummary({
        id: 't1',
        name: 'Daily Digest',
        type: 'recurring',
        enabled: true,
      }),
    },
    null,
    2,
  );
}
