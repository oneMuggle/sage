// src/widgets/chat/SubagentLivePanel.tsx
import { ChevronDown } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import { useTerminalPanelStore } from '../../features/terminal-panel/terminalPanelStore';

export function SubagentLivePanel({ sessionId }: { sessionId: string | null | undefined }) {
  const taskBoard = useChatStreamStore((s) => selectSessionSlots(s, sessionId).taskBoard);
  const isLoading = useChatStreamStore((s) => {
    const slots = selectSessionSlots(s, sessionId);
    return slots.streaming !== null && slots.streaming.state !== 'done';
  });
  const terminalOpen = useTerminalPanelStore((s) => s.open);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (terminalOpen) setCollapsed(true);
  }, [terminalOpen]);

  if (!isLoading || !taskBoard) return null;

  const rows = taskBoard.plan
    .map((item) => ({ item, live: taskBoard.live?.[item.task_id] }))
    .filter(
      ({ item, live }) =>
        taskBoard.statuses[item.task_id]?.status === 'running' && Boolean(live?.liveStep),
    );

  if (rows.length === 0) return null;

  return (
    <div
      data-testid="subagent-live-panel"
      className="mx-auto max-w-3xl mb-1.5 px-3 py-1.5 rounded-radius-sm border border-border bg-bg-subtle text-ui-2xs leading-relaxed"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted">
          子代理实时执行（{rows.length} 个运行中 · 详情点右侧任务树展开）
        </span>
        <button
          type="button"
          data-testid="subagent-live-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? '展开子代理实时进度' : '折叠子代理实时进度'}
          onClick={() => setCollapsed((v) => !v)}
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-text-tertiary hover:text-text hover:bg-bg-hover transition-colors"
        >
          <span>{collapsed ? '展开' : '收起'}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          />
        </button>
      </div>
      {!collapsed && (
        <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
          {rows.map(({ item, live }) => (
            <li key={item.task_id} className="flex items-center gap-2 min-w-0">
              <span className="text-primary animate-pulse shrink-0">◐</span>
              <span className="text-text-tertiary shrink-0">
                [{item.task_id} · {item.agent_id}]
              </span>
              <span className="text-text-secondary truncate">{live!.liveStep}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
