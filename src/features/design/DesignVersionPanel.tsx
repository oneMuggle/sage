/**
 * DesignVersionPanel — 版本时间线：预览 / 恢复历史版本。
 */
import { Loader2, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useDesignStore } from '../../entities/design/designStore';
import { useI18n } from '../../shared/lib/i18n';

interface DesignVersionPanelProps {
  projectId: string;
}

export function DesignVersionPanel({ projectId }: DesignVersionPanelProps) {
  const { t } = useI18n();
  const artifacts = useDesignStore((s) => s.artifacts);
  const previewArtifact = useDesignStore((s) => s.previewArtifact);
  const loading = useDesignStore((s) => s.loadingProject);
  const previewVersion = useDesignStore((s) => s.previewVersion);
  const restoreVersion = useDesignStore((s) => s.restoreVersion);
  const [restoring, setRestoring] = useState<string | null>(null);

  const ordered = [...artifacts].sort((a, b) => b.version - a.version);

  const handleRestore = async (artifactId: string) => {
    setRestoring(artifactId);
    try {
      await restoreVersion(projectId, artifactId);
      if (!useDesignStore.getState().errorProject) {
        toast.success(t('design.version.restored'));
      }
    } finally {
      setRestoring(null);
    }
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-3 py-2 text-ui-sm font-medium text-text">
        {t('design.detail.history')}
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {ordered.length === 0 ? (
          <p className="text-ui-xs text-text-tertiary">{t('design.version.empty')}</p>
        ) : (
          ordered.map((artifact) => (
            <div
              key={artifact.id}
              className={`rounded-md border px-2.5 py-2 text-ui-xs ${
                previewArtifact?.id === artifact.id
                  ? 'border-accent bg-accent/5'
                  : 'border-border'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-text">v{artifact.version}</span>
                <span className="truncate text-text-tertiary">{artifact.title}</span>
              </div>
              <div className="mt-0.5 text-text-tertiary">
                {new Date(artifact.created_at).toLocaleString()}
              </div>
              <div className="mt-1.5 flex gap-2">
                <button
                  type="button"
                  className="rounded border border-border px-2 py-0.5 hover:bg-surface-hover"
                  onClick={() => void previewVersion(projectId, artifact.id)}
                >
                  {t('design.version.preview')}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 hover:bg-surface-hover disabled:opacity-40"
                  disabled={loading || restoring !== null}
                  onClick={() => void handleRestore(artifact.id)}
                >
                  {restoring === artifact.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <RotateCcw className="h-3 w-3" />
                  )}
                  {t('design.version.restore')}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
