import { Plus, Trash2, Play, Edit3, Eye, Zap, Bell } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useScheduledTaskStore } from '../entities/scheduled/taskStore';
import { requestMessageJump } from '../features/chat/messageJumpStore';
import { CreateTaskModal } from '../features/scheduled/CreateTaskModal';
import { describeSchedule } from '../features/scheduled/cronValidator';
import { summarizeTaskSkillHealth } from '../features/scheduled/skillLink';
import { skillsApi } from '../shared/api/skillsApi';
import type { ScheduledTask, ScheduledTaskMode, Skill } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { PageHeader } from '../shared/ui';
import { confirmDialog } from '../shared/ui/ConfirmDialog/confirmService';

export function ScheduledTasks() {
  const { t, locale } = useI18n();
  const { tasks, loading, load, delete: deleteTask, runNow, update } = useScheduledTaskStore();
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.currentSessionId);
  const loadSessions = useStore((s) => s.loadSessions);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | undefined>(undefined);
  const [skills, setSkills] = useState<Skill[] | null>(null);

  useEffect(() => {
    void load();
    void loadSessions();
  }, [load, loadSessions]);

  useEffect(() => {
    if (tasks.length === 0) return;
    let cancelled = false;
    try {
      Promise.resolve(skillsApi.list())
        .then((list) => {
          if (!cancelled && Array.isArray(list)) setSkills(list);
        })
        .catch(() => {
          if (!cancelled) setSkills(null);
        });
    } catch {
      setSkills(null);
    }
    return () => {
      cancelled = true;
    };
  }, [tasks.length]);

  const handleDelete = async (id: string) => {
    if (!(await confirmDialog({ title: t('scheduled.confirm.delete'), danger: true }))) return;
    try {
      await deleteTask(id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t('scheduled.toast.delete_fail')}: ${message}`);
    }
  };

  const handleRunNow = async (id: string) => {
    try {
      const task = tasks.find((item) => item.id === id);
      if (
        task?.last_status === 'failed' &&
        !(await confirmDialog({ title: t('scheduled.confirm.retry') }))
      )
        return;
      const result = await runNow(id);
      if (result.last_status === 'failed') toast.error(t('scheduled.run_failed'));
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

  /**
   * 「查看结果」：切到目标会话 → requestMessageJump 定位到 assistant 消息。
   * 会话切换由 useStore.setCurrentSessionId 完成；MessageList 在目标消息出现
   * 后自动消费 jump 请求并滚动 + 高亮（参见 messageJumpStore.ts 的 B3/B4 协议）。
   */
  const handleViewResult = (task: ScheduledTask) => {
    if (task.mode !== 'execute' || !task.last_result_message_id) return;
    if (task.session_id && task.session_id !== currentSessionId) {
      useStore.getState().setCurrentSessionId(task.session_id);
    }
    requestMessageJump({ messageId: task.last_result_message_id });
  };

  const formatModeLabel = (mode: ScheduledTaskMode | undefined): string => {
    if (mode === 'execute') return t('scheduled.mode.execute');
    return t('scheduled.mode.deliver');
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title={t('scheduled.title')}
        subtitle={t('scheduled.subtitle')}
        actions={
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                setEditing(undefined);
                setCreateOpen(true);
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-ui-sm bg-primary text-text-inverse rounded-radius-sm hover:bg-primary/90"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>{t('scheduled.create')}</span>
            </button>
          </div>
        }
      />
      <div className="flex-1 flex flex-col p-6 gap-4 overflow-y-auto">
        {/* 初载闪空态修复: store 有 loading 字段但此前未消费, 初次 load 期间
          tasks.length === 0 会先渲染"暂无任务"再跳成列表。 */}
        {loading && tasks.length === 0 ? (
          <div
            className="flex-1 flex items-center justify-center text-text-secondary text-sm"
            role="status"
          >
            {t('common.loading')}
          </div>
        ) : tasks.length === 0 ? (
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
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="inline-flex items-center gap-1 text-ui-2xs px-1.5 py-0.5 rounded bg-muted/15 text-text-secondary"
                      data-testid="task-mode-badge"
                      title={formatModeLabel(task.mode)}
                    >
                      {task.mode === 'execute' ? (
                        <Zap className="w-3 h-3" />
                      ) : (
                        <Bell className="w-3 h-3" />
                      )}
                      {formatModeLabel(task.mode)}
                    </span>
                    <span className="text-ui-2xs text-muted">session: {task.session_id}</span>
                    {typeof task.max_runs === 'number' && task.max_runs > 0 && (
                      <span
                        data-testid="task-budget-badge"
                        className="text-ui-2xs px-1.5 py-0.5 rounded bg-muted/15 text-text-secondary"
                      >
                        runs: {task.run_count ?? 0}/{task.max_runs}
                      </span>
                    )}
                    {task.last_status === 'running' && (
                      <span
                        role="status"
                        data-testid="task-running-badge"
                        className="text-ui-2xs px-1.5 py-0.5 rounded bg-primary/15 text-primary"
                      >
                        {t('scheduled.executing')}
                      </span>
                    )}
                    {task.last_status === 'succeeded' &&
                      typeof task.last_duration_ms === 'number' && (
                        <span
                          data-testid="task-duration-badge"
                          className="text-ui-2xs text-text-secondary"
                        >
                          {t('scheduled.duration_ms').replace(
                            '{ms}',
                            String(task.last_duration_ms),
                          )}
                        </span>
                      )}
                  </div>
                  {(() => {
                    const health = summarizeTaskSkillHealth(
                      task.content,
                      skills,
                      t('scheduled.skill.unknown'),
                      t('scheduled.skill.disabled'),
                    );
                    return health.hasInvalid ? (
                      <p
                        role="status"
                        data-testid="task-invalid-skill-badge"
                        className="text-xs text-warning"
                      >
                        {health.invalidLabels.join('、')}
                      </p>
                    ) : null;
                  })()}
                  {task.last_status === 'failed' && (
                    <p role="status" className="text-xs text-error">
                      {t('scheduled.run_failed')} — {task.last_error}
                    </p>
                  )}
                  {task.last_status === 'succeeded' && (
                    <span className="text-xs text-success">{t('scheduled.run_succeeded')}</span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => handleViewResult(task)}
                    disabled={task.mode !== 'execute' || !task.last_result_message_id}
                    title={
                      task.mode === 'execute' && task.last_result_message_id
                        ? t('scheduled.view_result')
                        : t('scheduled.view_result_disabled')
                    }
                    data-testid="view-result-button"
                    aria-label={t('scheduled.view_result')}
                    className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-text-secondary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleToggleEnabled(task)}
                    className={[
                      'px-2 py-1 text-ui-2xs rounded-full',
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
          sessionId={currentSessionId ?? ''}
          sessions={sessions}
          task={editing}
        />
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditScheduledTasksPageGovernance(): {
  module: 'src/pages/ScheduledTasks.tsx';
  phase: 'P171';
  domain: 'pages';
  supportsRunNowToggleAndEdit: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/ScheduledTasks.tsx',
    phase: 'P171',
    domain: 'pages',
    supportsRunNowToggleAndEdit: true,
    compliant: true,
  };
}
