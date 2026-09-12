// src/widgets/chat/RightPanel.tsx
import { X } from 'lucide-react';
import { memo, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { useConversationOutline } from '../../features/chat/useConversationOutline';
import type { TaskBoard } from '../../features/send-message/useChat';
import type { ToolCall } from '../../shared/lib/store';
import { useResizablePanel } from '../../shared/lib/useResizablePanel';

import { ConversationOutline } from './ConversationOutline';
import { ArtifactViewer } from './artifacts/ArtifactViewer';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ChangesSection } from './changes/ChangesSection';
import { ProgressSection } from './progress/ProgressSection';

interface RightPanelProps {
  open: boolean;
  onToggle: () => void;
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  sessionId: string | null;
  taskBoard?: TaskBoard | null; // 新增：编排任务板
  // Wave 3 (2026-08-14): 计划卡接线回调透传。
  // M4 (2026-08-15): onPlanStart 已删。
  // Wave 4 (2026-09-06): onResumeRun 已删 —— 历史编排记录功能移除。
  onCancelExecution?: (runId: string) => void;
  // RV3 (round8): 终态且有失败任务时的重跑入口（透传 ProgressSection → TaskTreeSection）。
  onRerunFailed?: (runId: string) => void;
}

type Tab = 'progress' | 'artifacts' | 'changes' | 'outline';

const TAB_LABELS: Record<Tab, string> = {
  progress: '进度',
  artifacts: '产物',
  changes: '变更',
  outline: '目录',
};

interface PanelHeaderProps {
  tab?: Tab;
  onTabChange?: (t: Tab) => void;
  onClose: () => void;
}

export function PanelHeader({ tab, onTabChange, onClose }: PanelHeaderProps) {
  // list 视图:Progress / Artifacts tabs + × 按钮
  if (tab !== undefined && onTabChange) {
    return (
      <div className="flex border-b border-border items-center">
        {(['progress', 'outline', 'changes', 'artifacts'] as Tab[]).map((t) => (
          <button
            key={t}
            className={
              'flex-1 py-2 text-sm font-medium transition-colors ' +
              (tab === t
                ? 'text-primary border-b-2 border-primary'
                : 'text-text-secondary hover:text-text')
            }
            onClick={() => onTabChange(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
        <button
          className="ml-auto p-2 mr-1 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
          onClick={onClose}
          title="关闭右侧面板"
          aria-label="关闭右侧面板"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    );
  }

  // ArtifactViewer 视图:仅 × 按钮
  return (
    <div className="flex justify-end border-b border-border items-center h-10 px-2">
      <button
        className="p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
        onClick={onClose}
        title="关闭右侧面板"
        aria-label="关闭右侧面板"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

function RightPanelInner({
  open,
  onToggle,
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  sessionId,
  taskBoard,
  onCancelExecution,
  onRerunFailed,
}: RightPanelProps) {
  const [tab, setTab] = useState<Tab>('progress');
  const [selected, setSelected] = useState<Artifact | null>(null);
  const { artifacts, loading, refresh } = useArtifacts(sessionId);
  const { items: outlineItems, isLoading: outlineLoading } = useConversationOutline(sessionId);
  // P0-3 (UI 优化方案 2026-09-12): 面板宽度可调 —— 拖拽左边缘手柄，
  // 持久化到 localStorage（范围 280~600，默认 320）。
  const { width, onMouseDown: onResizeMouseDown } = useResizablePanel({
    storageKey: 'right-panel-width',
    minWidth: 280,
    maxWidth: 600,
    defaultWidth: 320,
    anchor: 'right',
  });

  return (
    <aside
      className={
        'fixed top-12 right-0 h-[calc(100vh-3rem)] bg-surface border-l border-border ' +
        'transform transition-transform duration-200 ease-in-out z-30 ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
      style={{ width: `${width}px` }}
    >
      {/* P0-3: 左边缘拖拽手柄 —— 悬停时高亮 + cursor-col-resize 反馈 */}
      <div
        className="absolute top-0 left-0 h-full w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
        onMouseDown={onResizeMouseDown}
        aria-label="拖拽调整面板宽度"
        data-testid="right-panel-resize-handle"
      />
      {selected ? (
        <PanelHeader onClose={onToggle} />
      ) : (
        <PanelHeader tab={tab} onTabChange={setTab} onClose={onToggle} />
      )}

      <div className="h-[calc(100%-2.5rem)] overflow-y-auto min-h-0">
        {selected && sessionId ? (
          <ArtifactViewer
            artifact={selected}
            sessionId={sessionId}
            onBack={() => setSelected(null)}
          />
        ) : tab === 'progress' ? (
          <ProgressSection
            iteration={iteration}
            streamingState={streamingState}
            toolCalls={toolCalls}
            isLoading={isLoading}
            taskBoard={taskBoard}
            // S2: todos 从该会话的键控槽位读取（切会话看该会话的清单）
            sessionId={sessionId}
            onCancelExecution={onCancelExecution}
            onRerunFailed={onRerunFailed}
          />
        ) : tab === 'changes' ? (
          <ChangesSection sessionId={sessionId} />
        ) : tab === 'outline' ? (
          <ConversationOutline items={outlineItems} isLoading={outlineLoading} />
        ) : (
          <ArtifactsSection
            artifacts={artifacts}
            loading={loading}
            sessionId={sessionId}
            onRefresh={refresh}
            onSelect={setSelected}
            onReveal={(a) => {
              if (sessionId) revealArtifact(sessionId, a.id).catch(() => {});
            }}
          />
        )}
      </div>
    </aside>
  );
}

// memo (F1): 面板关闭时仅平移出屏不卸载, memo 避免流式期间无意义的整面板重渲染。
export const RightPanel = memo(RightPanelInner);
