// src/widgets/chat/artifacts/ArtifactsSection.tsx
import { RefreshCw, FolderOpen } from 'lucide-react';

import type { Artifact } from '../../../features/artifacts/artifactApi';

import { ArtifactRow } from './ArtifactRow';

interface ArtifactsSectionProps {
  artifacts: Artifact[];
  loading: boolean;
  sessionId: string | null;
  onRefresh: () => void;
  onSelect: (artifact: Artifact) => void;
  onReveal: (artifact: Artifact) => void;
}

export function ArtifactsSection({
  artifacts, loading, sessionId, onRefresh, onSelect, onReveal,
}: ArtifactsSectionProps) {
  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-end gap-1 px-2 py-1 border-b border-border">
        {artifacts.length > 0 && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
            title="在文件管理器中显示"
            onClick={() => onReveal(artifacts[0])}
          >
            <FolderOpen className="w-4 h-4" />
          </button>
        )}
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
          title="刷新"
          aria-label="刷新"
          onClick={onRefresh}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {artifacts.length === 0 ? (
          <div className="p-3 text-sm text-muted">暂无产物</div>
        ) : (
          <div className="divide-y divide-border">
            {artifacts.map((a) => (
              <ArtifactRow key={a.id} artifact={a} onSelect={onSelect} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
