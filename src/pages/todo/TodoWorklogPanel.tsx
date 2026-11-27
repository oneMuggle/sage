/**
 * TodoWorklogPanel — 工作日志面板（P2）。
 *
 * 待办记「要做什么」，工作日志记「做过了什么」。两者一起构成日报 / 周报的
 * 双数据源。面板分三段：
 *
 * 1. **手动添加** —— 直接记一条（用户自己写的就是确定的事实，落库即确认）；
 * 2. **收件箱** —— 对话抽取出的待确认候选，逐条确认（进报告）或忽略；
 * 3. **日志流** —— 已确认记录，按自然日分组倒序排列，可改可删。
 *
 * 状态机的质量闸门在收件箱：抽取可能误记，只有 ``confirmed`` 才进统计。
 */
import { Check, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import type { WorkLog, WorkLogKind } from '../../shared/api/types';
import { worklogClient } from '../../shared/api/worklogClient';

const INBOX_LIMIT = 50;
const STREAM_LIMIT = 200;

const KIND_ORDER: WorkLogKind[] = ['progress', 'done', 'blocker', 'next'];

const KIND_LABELS: Record<WorkLogKind, string> = {
  progress: '进展',
  done: '完成',
  blocker: '阻塞',
  next: '下一步',
};

const KIND_CLASSES: Record<WorkLogKind, string> = {
  progress: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  done: 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  blocker: 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  next: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
};

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** 从 ``2026-11-27T14:32:05.123456`` 取日期键 ``2026-11-27``。 */
function dayKeyOf(createdAt: string): string {
  return createdAt.slice(0, 10);
}

/** 从 ISO 时间取 ``14:32``；解析不出时原样返回前 16 字符。 */
function timeOf(createdAt: string): string {
  const match = /T(\d{2}:\d{2})/.exec(createdAt);
  return match ? match[1] : createdAt.slice(0, 16);
}

/** ``2026-11-27`` → ``11 月 27 日 周四``；解析失败时原样返回。 */
function formatDayLabel(dayKey: string): string {
  const date = new Date(`${dayKey}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dayKey;
  const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()];
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${weekday}`;
}

interface DayGroup {
  dayKey: string;
  items: WorkLog[];
}

/** 按自然日分组（输入已按时间倒序，分组后组间顺序保持不变）。 */
function groupByDay(items: WorkLog[]): DayGroup[] {
  const groups: DayGroup[] = [];
  const index = new Map<string, DayGroup>();
  for (const item of items) {
    const dayKey = dayKeyOf(item.created_at);
    let group = index.get(dayKey);
    if (!group) {
      group = { dayKey, items: [] };
      index.set(dayKey, group);
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

export function TodoWorklogPanel() {
  const [inbox, setInbox] = useState<WorkLog[]>([]);
  const [stream, setStream] = useState<WorkLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [draft, setDraft] = useState('');
  const [draftKind, setDraftKind] = useState<WorkLogKind>('progress');
  const [adding, setAdding] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState('');

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [pendingRes, confirmedRes] = await Promise.all([
        worklogClient.list({ status: 'pending', limit: INBOX_LIMIT }),
        worklogClient.list({ status: 'confirmed', limit: STREAM_LIMIT }),
      ]);
      setInbox(pendingRes.items);
      setStream(confirmedRes.items);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleAdd = useCallback(async () => {
    const content = draft.trim();
    if (!content || adding) return;
    setAdding(true);
    setError(null);
    try {
      // 手动录入是用户主动陈述的事实，落库即确认，不进收件箱。
      const created = await worklogClient.create({ content, kind: draftKind });
      await worklogClient.confirm(created.id);
      setDraft('');
      setDraftKind('progress');
      await refresh();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }, [draft, draftKind, adding, refresh]);

  const handleConfirm = useCallback(
    async (id: number) => {
      setBusyId(id);
      setError(null);
      try {
        await worklogClient.confirm(id);
        await refresh();
      } catch (err: unknown) {
        setError(errorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [refresh],
  );

  const handleDismiss = useCallback(
    async (id: number) => {
      setBusyId(id);
      setError(null);
      try {
        await worklogClient.dismiss(id);
        await refresh();
      } catch (err: unknown) {
        setError(errorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (id: number) => {
      setBusyId(id);
      setError(null);
      try {
        await worklogClient.delete(id);
        if (editingId === id) setEditingId(null);
        await refresh();
      } catch (err: unknown) {
        setError(errorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [editingId, refresh],
  );

  const startEdit = useCallback((log: WorkLog) => {
    setEditingId(log.id);
    setEditText(log.content);
  }, []);

  const saveEdit = useCallback(
    async (id: number) => {
      const content = editText.trim();
      if (!content) return;
      setBusyId(id);
      setError(null);
      try {
        await worklogClient.update(id, { content });
        setEditingId(null);
        await refresh();
      } catch (err: unknown) {
        setError(errorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [editText, refresh],
  );

  const groups = useMemo(() => groupByDay(stream), [stream]);

  return (
    <div className="flex flex-col gap-4" data-testid="todo-worklog-panel">
      {/* 手动添加 */}
      <section className="rounded-radius-sm border border-border bg-ui-card p-3">
        <label htmlFor="worklog-draft" className="block text-ui-xs text-text-muted mb-1.5">
          记一条工作日志
        </label>
        <textarea
          id="worklog-draft"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="今天做了什么、卡在哪、下一步…"
          rows={2}
          maxLength={2000}
          className="w-full resize-y rounded border border-border bg-transparent px-2 py-1.5 text-sm text-text focus:border-primary focus:outline-none"
          data-testid="worklog-draft"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            {KIND_ORDER.map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => setDraftKind(kind)}
                aria-pressed={draftKind === kind}
                className={`px-2 py-0.5 rounded text-ui-xs border ${
                  draftKind === kind
                    ? 'border-primary text-primary'
                    : 'border-border text-text-muted hover:border-primary'
                }`}
                data-testid={`worklog-kind-${kind}`}
              >
                {KIND_LABELS[kind]}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void handleAdd()}
            disabled={!draft.trim() || adding}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-primary/10 text-primary text-ui-xs hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="worklog-add"
          >
            {adding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            添加
          </button>
        </div>
      </section>

      {error && (
        <div className="px-3 py-2 bg-red-50 text-red-700 text-sm rounded" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-2" role="status">
          <Loader2 className="w-4 h-4 animate-spin" />
          加载工作日志…
        </div>
      )}

      {/* 收件箱：对话抽取的待确认候选 */}
      {!loading && inbox.length > 0 && (
        <section
          className="rounded-radius-sm border border-primary/20 bg-primary/5 p-3"
          data-testid="worklog-inbox"
        >
          <h3 className="text-ui-xs text-text-muted mb-2">
            收件箱 · {inbox.length} 条待确认
            <span className="ml-1 opacity-70">（确认后才计入报告）</span>
          </h3>
          <ul className="flex flex-col gap-1.5">
            {inbox.map((log) => (
              <li
                key={log.id}
                className="flex items-start gap-2 px-2 py-1.5 rounded bg-ui-card border border-border"
                data-testid={`worklog-inbox-item-${log.id}`}
              >
                <span
                  className={`shrink-0 px-1.5 py-0.5 rounded text-ui-2xs ${KIND_CLASSES[log.kind]}`}
                >
                  {KIND_LABELS[log.kind]}
                </span>
                <span className="flex-1 text-sm text-text break-words">{log.content}</span>
                <span className="shrink-0 text-ui-2xs text-text-muted">
                  {timeOf(log.created_at)}
                </span>
                <button
                  type="button"
                  onClick={() => void handleConfirm(log.id)}
                  disabled={busyId === log.id}
                  title="确认（计入报告）"
                  aria-label="确认"
                  className="shrink-0 p-0.5 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded disabled:opacity-40"
                  data-testid={`worklog-confirm-${log.id}`}
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => void handleDismiss(log.id)}
                  disabled={busyId === log.id}
                  title="忽略"
                  aria-label="忽略"
                  className="shrink-0 p-0.5 text-text-muted hover:bg-bg-muted rounded disabled:opacity-40"
                  data-testid={`worklog-dismiss-${log.id}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 日志流：已确认记录，按日分组 */}
      {!loading && stream.length === 0 && (
        <p className="text-text-muted text-center py-6" data-testid="worklog-empty">
          还没有工作日志。随时记一条，或从对话里抽取。
        </p>
      )}

      {!loading &&
        groups.map((group) => (
          <section key={group.dayKey} data-testid={`worklog-day-${group.dayKey}`}>
            <h3 className="text-ui-xs text-text-muted mb-1.5">{formatDayLabel(group.dayKey)}</h3>
            <ul className="flex flex-col gap-1.5">
              {group.items.map((log) => (
                <li
                  key={log.id}
                  className="flex items-start gap-2 px-2 py-1.5 rounded border border-border bg-ui-card"
                  data-testid={`worklog-item-${log.id}`}
                >
                  <span className="shrink-0 text-ui-2xs text-text-muted pt-0.5 w-9">
                    {timeOf(log.created_at)}
                  </span>
                  <span
                    className={`shrink-0 px-1.5 py-0.5 rounded text-ui-2xs ${KIND_CLASSES[log.kind]}`}
                  >
                    {KIND_LABELS[log.kind]}
                  </span>
                  {editingId === log.id ? (
                    <input
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void saveEdit(log.id);
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      maxLength={2000}
                      autoFocus
                      className="flex-1 rounded border border-border bg-transparent px-2 py-0.5 text-sm text-text focus:border-primary focus:outline-none"
                      data-testid={`worklog-edit-input-${log.id}`}
                    />
                  ) : (
                    <span className="flex-1 text-sm text-text break-words">{log.content}</span>
                  )}
                  {editingId === log.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => void saveEdit(log.id)}
                        disabled={busyId === log.id || !editText.trim()}
                        title="保存"
                        aria-label="保存"
                        className="shrink-0 p-0.5 text-primary hover:bg-primary/10 rounded disabled:opacity-40"
                        data-testid={`worklog-edit-save-${log.id}`}
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        title="取消"
                        aria-label="取消编辑"
                        className="shrink-0 p-0.5 text-text-muted hover:bg-bg-muted rounded"
                        data-testid={`worklog-edit-cancel-${log.id}`}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => startEdit(log)}
                        title="编辑"
                        aria-label="编辑"
                        className="shrink-0 p-0.5 text-text-muted hover:bg-bg-muted rounded"
                        data-testid={`worklog-edit-${log.id}`}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDelete(log.id)}
                        disabled={busyId === log.id}
                        title="删除"
                        aria-label="删除"
                        className="shrink-0 p-0.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded disabled:opacity-40"
                        data-testid={`worklog-delete-${log.id}`}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
    </div>
  );
}
