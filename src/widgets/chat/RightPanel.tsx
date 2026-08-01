// src/widgets/chat/RightPanel.tsx
import { useState } from 'react';
import type { ToolCall } from '../../shared/lib/store';
import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { ProgressSection } from './progress/ProgressSection';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ArtifactViewer } from './artifacts/ArtifactViewer';

interface RightPanelProps {
  open: boolean;
  onToggle: () => void;
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  sessionId: string | null;
}

type Tab = 'progress' | 'artifacts';

export function RightPanel({
  open, iteration, streamingState, toolCalls, isLoading, sessionId,
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
      {!selected && (
        <div className="flex border-b border-border">
          {(['progress', 'artifacts'] as Tab[]).map((t) => (
            <button
              key={t}
              className={
                'flex-1 py-2 text-sm font-medium transition-colors ' +
                (tab === t
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text')
              }
              onClick={() => setTab(t)}
            >
              {t === 'progress' ? 'Progress' : 'Artifacts'}
            </button>
          ))}
        </div>
      )}

      <div className="h-[calc(100%-2.5rem)]">
        {selected && sessionId ? (
          <ArtifactViewer artifact={selected} sessionId={sessionId} onBack={() => setSelected(null)} />
        ) : tab === 'progress' ? (
          <ProgressSection
            iteration={iteration}
            streamingState={streamingState}
            toolCalls={toolCalls}
            isLoading={isLoading}
          />
        ) : (
          <ArtifactsSection
            artifacts={artifacts}
            loading={loading}
            sessionId={sessionId}
            onRefresh={refresh}
            onSelect={setSelected}
            onReveal={(a) => sessionId && revealArtifact(sessionId, a.id)}
          />
        )}
      </div>
    </aside>
  );
}
