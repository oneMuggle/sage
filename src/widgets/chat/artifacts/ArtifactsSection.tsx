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
  artifacts,
  loading,
  sessionId,
  onRefresh,
  onSelect,
  onReveal,
}: ArtifactsSectionProps) {
  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }

  // P2-3.11: 双击 Artifact → 弹出独立窗口 (仅 HTML 类型)
  const handleDoubleClick = (artifact: Artifact) => {
    if (!window.electronAPI?.openArtifactWindow) return;
    // artifact.path 来自后端,格式: /abs/path/to/artifact.html
    window.electronAPI
      .openArtifactWindow({
        id: artifact.id,
        name: artifact.name,
        kind: artifact.kind,
        path: artifact.path,
      })
      .catch(() => {
        // 静默失败:不支持的类型或 IPC 错误
      });
  };

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
          // R2 批次 C: 空态引导 —— 告诉用户产物从哪来（对齐主流空态文案）
          <div className="p-3 text-sm text-muted" data-testid="artifacts-empty">
            暂无产物
            <div className="mt-1 text-xs text-muted/80">
              让 agent 写文件或生成文档后，产物会自动出现在这里
            </div>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {artifacts.map((a) => (
              <ArtifactRow
                key={a.id}
                artifact={a}
                onSelect={onSelect}
                onDoubleClick={handleDoubleClick}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
