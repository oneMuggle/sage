import { Plus, Trash2, Play, Edit3 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useScheduledTaskStore } from '../entities/scheduled/taskStore';
import { CreateTaskModal } from '../features/scheduled/CreateTaskModal';
import { describeSchedule } from '../features/scheduled/cronValidator';
import type { ScheduledTask } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';

export function ScheduledTasks() {
  const { t, locale } = useI18n();
  const { tasks, load, delete: deleteTask, runNow, update } = useScheduledTaskStore();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | undefined>(undefined);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('scheduled.confirm.delete'))) return;
    try {
      await deleteTask(id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t('scheduled.toast.delete_fail')}: ${message}`);
    }
  };

  const handleRunNow = async (id: string) => {
    try {
      await runNow(id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    }
  };

  const handleToggleEnabled = async (task: ScheduledTask) => {
    try {
      await update(task.id, { enabled: !task.enabled });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    }
  };

  return (
    <div className="flex flex-col h-full p-6 gap-4 overflow-y-auto">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-text">{t('scheduled.title')}</h1>
          <p className="text-xs text-text-secondary">{t('scheduled.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditing(undefined);
            setCreateOpen(true);
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary/90"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>{t('scheduled.create')}</span>
        </button>
      </header>

      {tasks.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-secondary text-sm">
          {t('scheduled.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="task-list">
          {tasks.map((task) => (
            <li
              key={task.id}
              className="flex items-center justify-between gap-3 p-3 bg-surface border border-border rounded-radius-md"
            >
              <div className="flex flex-col min-w-0 flex-1">
                <span className="text-sm font-medium text-text truncate">{task.name}</span>
                <span className="text-xs text-text-secondary truncate">
                  {describeSchedule(task.schedule, locale as 'zh' | 'en')}
                </span>
                <span className="text-[10px] text-muted">session: {task.session_id}</span>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => handleToggleEnabled(task)}
                  className={[
                    'px-2 py-1 text-[11px] rounded-full',
                    task.enabled ? 'bg-success/10 text-success' : 'bg-muted/20 text-muted',
                  ].join(' ')}
                >
                  {task.enabled ? t('scheduled.status.enabled') : t('scheduled.status.disabled')}
                </button>
                <button
                  type="button"
                  onClick={() => handleRunNow(task.id)}
                  title={t('scheduled.action.run_now')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-text-secondary hover:bg-bg-hover"
                >
                  <Play className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(task);
                    setCreateOpen(true);
                  }}
                  title={t('scheduled.edit')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-text-secondary hover:bg-bg-hover"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(task.id)}
                  title={t('common.delete')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-error hover:bg-error/10"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <CreateTaskModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        sessionId="default"
        task={editing}
      />
    </div>
  );
}
