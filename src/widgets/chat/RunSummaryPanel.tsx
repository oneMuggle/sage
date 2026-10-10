// src/widgets/chat/RunSummaryPanel.tsx
import { AlertTriangle, CheckCircle2, ChevronDown, FileCode2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useChangesListStore } from '../../features/changes/changesListStore';
import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import { useTerminalPanelStore } from '../../features/terminal-panel/terminalPanelStore';

interface RunSummaryPanelProps {
  sessionId: string | null | undefined;
  /** 重跑失败任务 —— 复用既有 rerun-failed 通路（Chat.tsx 的 handleRerunFailed） */
  onRerunFailed?: () => void;
}

export function RunSummaryPanel({ sessionId, onRerunFailed }: RunSummaryPanelProps) {
  const taskBoard = useChatStreamStore((s) => selectSessionSlots(s, sessionId).taskBoard);
  const isRunning = useChatStreamStore((s) => {
    const slots = selectSessionSlots(s, sessionId);
    return slots.streaming !== null && slots.streaming.state !== 'done';
  });

  const changes = useChangesListStore((s) => (sessionId ? s.bySession[sessionId] : undefined));
  const changesError = useChangesListStore((s) => (sessionId ? s.errors[sessionId] : undefined));
  const fetchChanges = useChangesListStore((s) => s.fetch);
  const terminalOpen = useTerminalPanelStore((s) => s.isOpen);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (terminalOpen) setCollapsed(true);
  }, [terminalOpen]);

  useEffect(() => {
    // 终态才拉：跑的过程中逐条 refetch 会和写工具的 workspace_changed 事件打架。
    if (sessionId && !isRunning) void fetchChanges(sessionId);
  }, [sessionId, isRunning, fetchChanges]);

  // 只在「编排 run 已结束」时出现；普通对话没有 taskBoard，不受影响。
  if (isRunning || !taskBoard) return null;

  const progress = taskBoard.progress;
  const failedTasks = Object.values(taskBoard.statuses ?? {}).filter(
    (s) => s.status === 'failed' || s.status === 'cancelled',
  );
  const fileCount = changes?.changes.length ?? 0;

  // 三个维度全空 → 没有可汇报的内容，不渲染空壳。
  if (!progress && failedTasks.length === 0 && fileCount === 0 && !changesError) return null;

  return (
    <section
      data-testid="run-summary-panel"
      aria-label="运行摘要"
      className="mx-auto mb-1.5 max-w-3xl rounded-radius-sm border border-border bg-bg-subtle px-3 py-2 text-ui-2xs leading-relaxed"
    >
      <div className="flex items-center gap-2 text-ui-xs font-medium text-text">
        {failedTasks.length > 0 ? (
          <AlertTriangle className="h-3.5 w-3.5 text-warning shrink-0" aria-hidden="true" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-success shrink-0" aria-hidden="true" />
        )}
        <span>本次运行</span>
        {progress ? (
          <span className="font-normal text-text-secondary" data-testid="run-summary-progress">
            共 {progress.total} 个子任务 · 完成 {progress.done}
            {progress.failed > 0 ? ` · 失败 ${progress.failed}` : ''}
            {progress.cancelled > 0 ? ` · 取消 ${progress.cancelled}` : ''}
          </span>
        ) : null}
        <button
          type="button"
          data-testid="run-summary-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? '展开运行摘要' : '收起运行摘要'}
          onClick={() => setCollapsed((v) => !v)}
          className="ml-auto inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-ui-2xs font-normal text-text-tertiary hover:text-text hover:bg-bg-hover transition-colors"
        >
          <span>{collapsed ? '展开' : '收起'}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          />
        </button>
      </div>

      {!collapsed && (
        <div className="mt-1.5 max-h-40 overflow-y-auto space-y-1.5">
          {failedTasks.length > 0 ? (
            <div data-testid="run-summary-failures">
              <div className="mb-0.5 text-text-tertiary">未完成的任务</div>
              <ul className="space-y-0.5">
                {failedTasks.map((task) => (
                  <li key={task.task_id} className="flex flex-wrap items-baseline gap-1.5">
                    <span className="text-text-secondary">
                      [{task.agent_id}] {task.goal}
                    </span>
                    {task.retry_count && task.retry_count > 0 ? (
                      <span className="text-text-tertiary">已重试 {task.retry_count} 次</span>
                    ) : null}
                    {task.error ? (
                      <span className="text-error" data-testid="run-summary-error">
                        {task.error}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {onRerunFailed ? (
                <button
                  type="button"
                  data-testid="run-summary-rerun"
                  onClick={onRerunFailed}
                  className="mt-1 rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover hover:text-text"
                >
                  重跑失败任务
                </button>
              ) : null}
            </div>
          ) : null}

          {changesError ? (
            <p className="text-text-tertiary" data-testid="run-summary-changes-error">
              无法读取文件变更：{changesError}
            </p>
          ) : fileCount > 0 ? (
            <div data-testid="run-summary-files">
              <div className="mb-0.5 flex items-center gap-1 text-text-tertiary">
                <FileCode2 className="h-3 w-3" aria-hidden="true" />
                <span>本次会话工作区变更 {fileCount} 个文件</span>
              </div>
              <ul className="space-y-0.5">
                {changes?.changes.slice(0, 8).map((change) => (
                  <li
                    key={change.path}
                    className="flex items-baseline gap-1.5 font-mono text-text-secondary"
                  >
                    <span className="truncate">{change.path}</span>
                    {typeof change.insertions === 'number' && change.insertions > 0 ? (
                      <span className="text-success">+{change.insertions}</span>
                    ) : null}
                    {typeof change.deletions === 'number' && change.deletions > 0 ? (
                      <span className="text-error">−{change.deletions}</span>
                    ) : null}
                  </li>
                ))}
                {fileCount > 8 ? (
                  <li className="text-text-tertiary">其余 {fileCount - 8} 个见右侧变更面板</li>
                ) : null}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

export default RunSummaryPanel;
