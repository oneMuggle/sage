// src/widgets/task-center/TaskCenterWidget.tsx
//
// P4 第一切片 (docs/plans/2026-09-13_ui-optimization-p4-task-center.md):
// 全局任务中心悬浮胶囊。聚合两类长任务：
//  - taskCenterStore 注册的页面任务（office 生成/导出等）
//  - 后台会话聊天流（直接读 chatStreamStore 会话槽位，单一事实源）
// 无活动任务不渲染；折叠态只显示计数胶囊，展开态列出可跳转的任务。

import { Loader2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

interface Entry {
  id: string;
  title: string;
  startedAt: number | null;
  route: string | null;
}

export function TaskCenterWidget() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const registryTasks = useTaskCenterStore((s) => s.tasks);
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const sessions = useStore((s) => s.sessions);

  const entries = useMemo<Entry[]>(() => {
    const chatEntries: Entry[] = Object.entries(streamSessions)
      .filter(([, slots]) => slots.streaming != null)
      .map(([id]) => ({
        id: `chat:${id}`,
        title:
          sessions.find((s) => s.id === id)?.title ?? t('taskCenter.chatFallback'),
        startedAt: null,
        route: `/chat?session=${encodeURIComponent(id)}`,
      }));
    const registryEntries: Entry[] = Object.values(registryTasks).map((task) => ({
      id: task.id,
      title: task.title,
      startedAt: task.startedAt,
      route: task.kind === 'office' ? '/office' : task.kind === 'wiki' ? '/knowledge' : null,
    }));
    return [...registryEntries, ...chatEntries];
  }, [registryTasks, streamSessions, sessions, t]);

  const busy = entries.length > 0;

  // 有活动任务时每秒跳动的时钟（驱动已耗时显示）；空闲时不跑定时器
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  if (!busy) return null;

  return (
    <div className="fixed bottom-4 right-4 z-40 flex flex-col items-end gap-2" data-testid="task-center">
      {expanded && (
        <div
          data-testid="task-center-list"
          className="max-h-72 min-w-56 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg p-1.5 flex flex-col gap-1"
        >
          {entries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => {
                setExpanded(false);
                if (entry.route) navigate(entry.route);
              }}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-left text-xs text-text hover:bg-bg-hover transition-colors max-w-64"
            >
              <Loader2 className="w-3.5 h-3.5 text-primary shrink-0 animate-spin" aria-hidden />
              <span className="truncate flex-1">{entry.title}</span>
              {entry.startedAt != null && (
                <span className="text-[10px] text-muted tabular-nums shrink-0">
                  {Math.max(0, Math.floor((now - entry.startedAt) / 1000))}s
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        data-testid="task-center-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface border border-border shadow-md text-xs text-text hover:bg-bg-hover transition-colors"
      >
        <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" aria-hidden />
        {t('taskCenter.activeCount').replace('{n}', String(entries.length))}
      </button>
    </div>
  );
}
