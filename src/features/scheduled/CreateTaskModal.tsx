import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useScheduledTaskStore } from '../../entities/scheduled/taskStore';
import type { CreateTaskInput, ScheduledTask } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

import { CronExpressionPicker } from './CronExpressionPicker';
import { validateCronExpression, validateOneShotTimestamp } from './cronValidator';

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  sessions?: Array<{ id: string; title?: string }>;
  task?: ScheduledTask;
}

function toLocalDatetimeInput(ms: number): string {
  const date = new Date(ms);
  const tz = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - tz).toISOString().slice(0, 16);
}

function fromLocalDatetimeInput(value: string): number {
  return new Date(value).getTime();
}

export function CreateTaskModal({
  open,
  onClose,
  sessionId,
  task,
  sessions = [{ id: sessionId }],
}: CreateTaskModalProps) {
  const { t } = useI18n();
  const store = useScheduledTaskStore();
  const isEdit = Boolean(task);

  const [name, setName] = useState(task?.name ?? '');
  const [type, setType] = useState<'once' | 'recurring'>(task?.type ?? 'recurring');
  const [cron, setCron] = useState(
    task?.schedule.kind === 'recurring' ? task.schedule.cron : '0 8 * * *',
  );
  const [atLocal, setAtLocal] = useState(() =>
    task?.schedule.kind === 'once'
      ? toLocalDatetimeInput(task.schedule.at)
      : toLocalDatetimeInput(Date.now() + 60_000),
  );
  const [content, setContent] = useState(task?.content ?? '');
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [targetSession, setTargetSession] = useState(task?.session_id ?? sessionId);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(task?.name ?? '');
    setType(task?.type ?? 'recurring');
    setCron(task?.schedule.kind === 'recurring' ? task.schedule.cron : '0 8 * * *');
    setAtLocal(
      toLocalDatetimeInput(task?.schedule.kind === 'once' ? task.schedule.at : Date.now() + 60_000),
    );
    setContent(task?.content ?? '');
    setEnabled(task?.enabled ?? true);
    setTargetSession(task?.session_id ?? sessionId);
    setError(null);
    setSubmitting(false);
  }, [open, task, sessionId]);

  const cronValidation = useMemo(() => validateCronExpression(cron), [cron]);
  // Preserve seconds/milliseconds when the minute-precision input is unchanged.
  const atMs =
    task?.schedule.kind === 'once' && atLocal === toLocalDatetimeInput(task.schedule.at)
      ? task.schedule.at
      : fromLocalDatetimeInput(atLocal);
  const scheduleChanged =
    !task ||
    type !== task.type ||
    (type === 'once'
      ? task.schedule.kind !== 'once' || atMs !== task.schedule.at
      : task.schedule.kind !== 'recurring' || cron !== task.schedule.cron);
  const requireFuture = !task || scheduleChanged || (enabled && !task.enabled);
  const atValidation =
    !requireFuture && Number.isFinite(atMs)
      ? { ok: true as const }
      : validateOneShotTimestamp(atMs);

  const canSubmit =
    name.trim().length > 0 &&
    content.trim().length > 0 &&
    targetSession.length > 0 &&
    sessions.some((s) => s.id === targetSession) &&
    (type === 'recurring' ? cronValidation.ok : atValidation.ok) &&
    !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    // Wall-clock validation must run at submit time, not only when input changes.
    if (type === 'once' && requireFuture) {
      const validation = validateOneShotTimestamp(atMs);
      if (!validation.ok) {
        setError(validation.reason);
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    const schedule: CreateTaskInput['schedule'] =
      type === 'recurring' ? { kind: 'recurring', cron } : { kind: 'once', at: atMs };

    try {
      if (isEdit && task) {
        await store.update(task.id, {
          name,
          enabled,
          type,
          schedule,
          content,
          session_id: targetSession,
        });
        toast.success(t('scheduled.edit'));
      } else {
        await store.create({ name, type, schedule, session_id: targetSession, content, enabled });
        toast.success(t('scheduled.create'));
      }
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      toast.error(isEdit ? t('scheduled.toast.update_fail') : t('scheduled.toast.create_fail'));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="bg-surface border border-border rounded-radius-md w-[460px] max-w-[92vw] p-5 shadow-xl flex flex-col gap-3"
      >
        <h2 className="text-base font-semibold text-text">
          {isEdit ? t('scheduled.edit') : t('scheduled.create')}
        </h2>

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          <span>{t('scheduled.field.name')}</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
            placeholder={t('scheduled.field.name')}
            required
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          <span>{t('scheduled.field.session')}</span>
          <select
            value={targetSession}
            onChange={(e) => setTargetSession(e.target.value)}
            required
            className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
          >
            <option value="">{t('scheduled.session.required')}</option>
            {sessions
              .filter((s) => s.id)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title || s.id}
                </option>
              ))}
          </select>
          {sessions.length === 0 && <p>{t('scheduled.session.empty')}</p>}
        </label>

        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => setType('once')}
            className={`flex-1 py-1.5 rounded-radius-sm border ${
              type === 'once'
                ? 'bg-primary/10 border-primary text-primary'
                : 'bg-surface border-border text-text-secondary'
            }`}
          >
            {t('scheduled.field.type.once')}
          </button>
          <button
            type="button"
            onClick={() => setType('recurring')}
            className={`flex-1 py-1.5 rounded-radius-sm border ${
              type === 'recurring'
                ? 'bg-primary/10 border-primary text-primary'
                : 'bg-surface border-border text-text-secondary'
            }`}
          >
            {t('scheduled.field.type.recurring')}
          </button>
        </div>

        {type === 'recurring' ? (
          <div className="flex flex-col gap-1 text-xs text-text-secondary">
            <span>{t('scheduled.field.cron')}</span>
            <CronExpressionPicker value={cron} onChange={setCron} disabled={submitting} />
          </div>
        ) : (
          <label className="flex flex-col gap-1 text-xs text-text-secondary">
            <span>{t('scheduled.field.at')}</span>
            <input
              type="datetime-local"
              value={atLocal}
              onChange={(e) => setAtLocal(e.target.value)}
              className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
            />
            {!atValidation.ok && <p className="text-error">{atValidation.reason}</p>}
          </label>
        )}

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          <span>{t('scheduled.field.content')}</span>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={3}
            className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg resize-none"
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>{t('scheduled.field.enabled')}</span>
        </label>

        {error && (
          <p className="text-xs text-error" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover rounded-radius-sm"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm disabled:opacity-50"
          >
            {isEdit ? t('common.save') : t('scheduled.create')}
          </button>
        </div>
      </form>
    </div>
  );
}
