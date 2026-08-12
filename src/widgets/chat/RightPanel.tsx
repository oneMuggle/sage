// src/widgets/chat/RightPanel.tsx
import { useState } from 'react';
import { X } from 'lucide-react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import type { TaskBoard } from '../../features/send-message/useChat';
import type { ToolCall } from '../../shared/lib/store';

import { ArtifactViewer } from './artifacts/ArtifactViewer';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
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
}

type Tab = 'progress' | 'artifacts';

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
        {(['progress', 'artifacts'] as Tab[]).map((t) => (
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
            {t === 'progress' ? 'Progress' : 'Artifacts'}
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

export function RightPanel({
  open,
  onToggle,
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  sessionId,
  taskBoard,
}: RightPanelProps) {
  const [tab, setTab] = useState<Tab>('progress');
  const [selected, setSelected] = useState<Artifact | null>(null);
  const { artifacts, loading, refresh } = useArtifacts(sessionId);

  return (
    <aside
      className={
        'fixed top-12 right-0 h-[calc(100vh-3rem)] w-80 bg-surface border-l border-border ' +
        'transform transition-transform duration-200 ease-in-out z-30 ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
    >
      {selected ? (
        <PanelHeader onClose={onToggle} />
      ) : (
        <PanelHeader tab={tab} onTabChange={setTab} onClose={onToggle} />
      )}

      <div className="h-[calc(100%-2.5rem)]">
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
          />
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
