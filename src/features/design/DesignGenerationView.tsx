/**
 * DesignGenerationView — 项目详情：iframe 预览 + 迭代聊天 + 导出。
 */
import { ArrowLeft, ChevronDown, Loader2, ShieldCheck, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectStatus } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';
import { HtmlPreviewHost } from '../../widgets/chat/preview/HtmlPreviewHost';

import { DesignExportPanel } from './DesignExportPanel';
import { DesignIterationChat } from './DesignIterationChat';
import { DesignProgressStrip } from './DesignProgressStrip';
import { DesignResourcesPanel } from './DesignResourcesPanel';
import { DesignTweaksPanel } from './DesignTweaksPanel';
import { DesignVersionPanel } from './DesignVersionPanel';
import { composeReviewFeedback } from './designReview';
import { applyTweaks } from './designTweaks';

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
      return 'bg-bg-hover text-text-secondary';
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
  const previewArtifact = useDesignStore((s) => s.previewArtifact);
  const clearPreview = useDesignStore((s) => s.clearPreview);
  const restoreVersion = useDesignStore((s) => s.restoreVersion);
  const tweaks = useDesignStore((s) => s.tweaks);
  const generationProgress = useDesignStore((s) => s.generationProgress);
  const review = useDesignStore((s) => s.review);
  const runReview = useDesignStore((s) => s.runReview);
  const iterate = useDesignStore((s) => s.iterate);
  const comparePair = useDesignStore((s) => s.comparePair);
  const clearCompare = useDesignStore((s) => s.clearCompare);
  const [panel, setPanel] = useState<'iterate' | 'history' | 'tweaks' | 'resources'>('iterate');
  const [reviewOpen, setReviewOpen] = useState(false);

  useEffect(() => {
    void loadProject(projectId);
    return () => clearCurrent();
  }, [projectId, loadProject, clearCurrent]);

  const handleGenerate = () => {
    void generate(projectId, project?.brief);
  };

  const shownArtifact = previewArtifact ?? artifact;

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ui-sm hover:bg-bg-hover"
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
            <span className="shrink-0 text-ui-xs text-text-muted">
              {t('design.detail.version').replace('{version}', String(artifact.version))}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <DesignExportPanel projectId={projectId} hasArtifact={Boolean(artifact)} />
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-ui-xs hover:bg-bg-hover disabled:opacity-40"
            disabled={!artifact || loading}
            onClick={() => {
              setReviewOpen(true);
              void runReview(projectId);
            }}
          >
            <ShieldCheck className="w-3 h-3" />
            {t('design.review.run')}
          </button>
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

      {loading && generationProgress && <DesignProgressStrip stage={generationProgress.stage} />}

      {review && (
        <div
          className={`mx-5 mt-2 rounded-md border px-3 py-1.5 text-ui-xs ${
            review.ok
              ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-600'
              : 'border-amber-500/30 bg-amber-500/5 text-amber-600'
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="truncate">
              {review.ok
                ? t('design.review.ok')
                : t('design.review.summary')
                    .replace('{errors}', String(review.error_count))
                    .replace('{warnings}', String(review.warning_count))}
            </span>
            {review.issues.length > 0 && !review.ok && (
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-0.5 rounded border border-current px-1.5 py-0.5 hover:underline disabled:opacity-40"
                disabled={loading}
                onClick={() => void iterate(projectId, composeReviewFeedback(review))}
              >
                {t('design.review.fix')}
              </button>
            )}
            {review.issues.length > 0 && (
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-0.5 hover:underline"
                onClick={() => setReviewOpen((prev) => !prev)}
              >
                <ChevronDown className={`h-3 w-3 transition ${reviewOpen ? 'rotate-180' : ''}`} />
                {t('design.review.details')}
              </button>
            )}
          </div>
          {reviewOpen && review.issues.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {review.issues.map((issue) => (
                <li key={`${issue.rule_id}-${issue.line ?? ''}`} className="truncate">
                  [{issue.severity === 'error' ? 'P0' : 'P1'}] {issue.rule_id}: {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-h-0 overflow-y-auto">
          {comparePair ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between rounded-md border border-border bg-surface px-3 py-1.5 text-ui-xs">
                <span className="text-text-secondary">{t('design.version.compareTitle')}</span>
                <button
                  type="button"
                  className="rounded border border-border px-2 py-0.5 hover:bg-bg-hover"
                  onClick={clearCompare}
                >
                  {t('design.version.compareClose')}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {[comparePair.left, comparePair.right].map((side) => (
                  <div key={side.id} className="min-w-0">
                    <div className="mb-1 text-ui-xs text-text-secondary">v{side.version}</div>
                    <HtmlPreviewHost
                      html={applyTweaks(side.html_content, tweaks)}
                      name={`v${side.version}.html`}
                      heightClassName="h-[calc(100vh-18rem)] min-h-[20rem]"
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <>
              {previewArtifact && (
                <div className="mb-2 flex items-center justify-between rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-ui-xs">
                  <span>
                    {t('design.detail.previewing').replace(
                      '{version}',
                      String(previewArtifact.version),
                    )}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded border border-border px-2 py-0.5 hover:bg-bg-hover"
                      onClick={clearPreview}
                    >
                      {t('design.detail.backToLatest')}
                    </button>
                    <button
                      type="button"
                      className="rounded border border-accent px-2 py-0.5 text-accent hover:bg-accent/5"
                      onClick={() => void restoreVersion(projectId, previewArtifact.id)}
                    >
                      {t('design.version.restore')}
                    </button>
                  </div>
                </div>
              )}
              {shownArtifact ? (
                <HtmlPreviewHost
                  html={applyTweaks(shownArtifact.html_content, tweaks)}
                  name={`${project?.name ?? 'design'}.html`}
                  heightClassName="h-[calc(100vh-14rem)] min-h-[24rem]"
                />
              ) : (
                <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-center text-ui-sm text-text-secondary">
                  {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                  <p>{loading ? t('design.detail.regenerating') : t('design.detail.noArtifact')}</p>
                </div>
              )}
            </>
          )}
        </section>
        <div className="flex min-h-0 flex-col gap-2">
          <div className="flex gap-1 rounded-md border border-border bg-surface p-1">
            {(['iterate', 'history', 'tweaks', 'resources'] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={panel === option}
                className={`flex-1 rounded px-2 py-1 text-ui-xs transition ${
                  panel === option
                    ? 'bg-accent/10 text-accent'
                    : 'text-text-secondary hover:bg-bg-hover'
                }`}
                onClick={() => setPanel(option)}
              >
                {option === 'iterate'
                  ? t('design.detail.tabIterate')
                  : option === 'history'
                    ? t('design.detail.tabHistory')
                    : option === 'tweaks'
                      ? t('design.detail.tabTweaks')
                      : t('design.detail.tabResources')}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {panel === 'iterate' ? (
              <DesignIterationChat projectId={projectId} />
            ) : panel === 'history' ? (
              <DesignVersionPanel projectId={projectId} />
            ) : panel === 'tweaks' ? (
              <DesignTweaksPanel projectId={projectId} />
            ) : (
              <DesignResourcesPanel projectId={projectId} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
