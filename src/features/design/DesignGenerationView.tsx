/**
 * DesignGenerationView — 项目详情：iframe 预览 + 迭代聊天 + 导出。
 */
import { ArrowLeft, Loader2, Sparkles } from 'lucide-react';
import { useEffect } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectStatus } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';
import { HtmlPreviewHost } from '../../widgets/chat/preview/HtmlPreviewHost';

import { DesignExportPanel } from './DesignExportPanel';
import { DesignIterationChat } from './DesignIterationChat';

interface DesignGenerationViewProps {
  projectId: string;
  onBack: () => void;
}

function statusClass(status: ProjectStatus): string {
  switch (status) {
    case 'complete':
      return 'bg-emerald-500/10 text-emerald-600';
    case 'generating':
      return 'bg-amber-500/10 text-amber-600';
    case 'error':
      return 'bg-red-500/10 text-red-600';
    default:
      return 'bg-surface-hover text-text-secondary';
  }
}

export function DesignGenerationView({ projectId, onBack }: DesignGenerationViewProps) {
  const { t } = useI18n();
  const project = useDesignStore((s) => s.currentProject);
  const artifact = useDesignStore((s) => s.currentArtifact);
  const loading = useDesignStore((s) => s.loadingProject);
  const error = useDesignStore((s) => s.errorProject);
  const loadProject = useDesignStore((s) => s.loadProject);
  const generate = useDesignStore((s) => s.generate);
  const clearCurrent = useDesignStore((s) => s.clearCurrent);

  useEffect(() => {
    void loadProject(projectId);
    return () => clearCurrent();
  }, [projectId, loadProject, clearCurrent]);

  const handleGenerate = () => {
    void generate(projectId, project?.brief);
  };

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ui-sm hover:bg-surface-hover"
            onClick={onBack}
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            {t('design.back')}
          </button>
          <span className="truncate text-ui-md font-medium text-text">
            {project?.name ?? projectId}
          </span>
          {project && (
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-ui-xs ${statusClass(project.status)}`}
            >
              {t(`design.status.${project.status}`)}
            </span>
          )}
          {artifact && (
            <span className="shrink-0 text-ui-xs text-text-tertiary">
              {t('design.detail.version').replace('{version}', String(artifact.version))}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <DesignExportPanel projectId={projectId} hasArtifact={Boolean(artifact)} />
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-ui-xs text-white disabled:opacity-40"
            disabled={loading}
            onClick={handleGenerate}
          >
            {loading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Sparkles className="w-3 h-3" />
            )}
            {loading
              ? t('design.detail.regenerating')
              : artifact
                ? t('design.detail.regenerate')
                : t('design.detail.generate')}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-5 mt-2 flex items-center justify-between rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-ui-sm text-red-600">
          <span className="truncate">{error}</span>
          <button
            type="button"
            className="ml-2 shrink-0 rounded border border-red-500/30 px-2 py-0.5 text-ui-xs hover:bg-red-500/10"
            onClick={() => void loadProject(projectId)}
          >
            {t('design.retry')}
          </button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-h-0 overflow-y-auto">
          {artifact ? (
            <HtmlPreviewHost
              html={artifact.html_content}
              name={`${project?.name ?? 'design'}.html`}
              heightClassName="h-[calc(100vh-14rem)] min-h-[24rem]"
            />
          ) : (
            <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-center text-ui-sm text-text-secondary">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              <p>{loading ? t('design.detail.regenerating') : t('design.detail.noArtifact')}</p>
            </div>
          )}
        </section>
        <DesignIterationChat projectId={projectId} />
      </div>
    </div>
  );
}
