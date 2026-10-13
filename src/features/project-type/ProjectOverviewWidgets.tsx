/**
 * 项目概览 Widget (2026-09-25; Phase P14 多态版本保护与阶段状态卡片 2026-10-12; Phase P20 L1 宪章就绪度与一键快照留痕 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.3
 * 根据项目类型与版本控制策略显示对应的概览 Widget、L1 宪章就绪状态及快捷快照按钮
 */

import { FileText, History, Layers, Plus } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi, type ProjectSummary } from '../../shared/api';

import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
import { GitStatusWidget } from './GitStatusWidget';
import { MilestoneProgressWidget } from './MilestoneProgressWidget';
import { ProjectAdvisorCard } from './ProjectAdvisorCard';
import { WikiGenerationPanel } from './WikiGenerationPanel';
import { getArchetypeBlueprint } from './archetypeBlueprints';

export interface ProjectOverviewWidgetsProps {
  project: ProjectSummary;
}

const VCS_MODE_LABELS: Record<string, string> = {
  git: 'Git 版本控制',
  builtin: '内置快照时间轴 (.sage/checkpoints)',
  none: '无版本控制',
};

export function ProjectOverviewWidgets({ project }: ProjectOverviewWidgetsProps) {
  const projectType = project.projectType;
  const blueprint = getArchetypeBlueprint(projectType);
  const [checkpointCount, setCheckpointCount] = useState<number>(0);
  const [hasSageMd, setHasSageMd] = useState<boolean | null>(null);
  const [totalFiles, setTotalFiles] = useState<number | null>(null);
  const [creatingSnapshot, setCreatingSnapshot] = useState(false);

  const loadOverviewMeta = useCallback(async () => {
    if (!project.id || typeof projectApi?.getWorkspaceOverview !== 'function') return;
    try {
      const ov = await projectApi.getWorkspaceOverview(project.id);
      setCheckpointCount(ov.recentCheckpoints?.length ?? 0);
      setHasSageMd(Boolean(ov.hasSageMd));
      setTotalFiles(Array.isArray(ov.directorySummary) ? ov.directorySummary.reduce((acc, d) => acc + (d.fileCount || 0), 0) : null);
    } catch {
      setCheckpointCount(0);
    }
  }, [project.id]);

  useEffect(() => {
    void loadOverviewMeta();
  }, [loadOverviewMeta]);

  const stageLabel =
    blueprint.stages.find((s) => s.id === project.projectStage)?.label ??
    project.projectStage ??
    blueprint.stages[0]?.label ??
    '默认阶段';

  const handleQuickCheckpoint = async () => {
    if (!project.id || creatingSnapshot || typeof projectApi?.createCheckpoint !== 'function') {
      return;
    }
    setCreatingSnapshot(true);
    try {
      await projectApi.createCheckpoint(project.id, `阶段快照：${stageLabel}`);
      await loadOverviewMeta();
    } catch {
      // ignore in test/offline mode
    } finally {
      setCreatingSnapshot(false);
    }
  };

  const vcsLabel =
    VCS_MODE_LABELS[project.vcsMode ?? ''] ??
    (projectType === 'coding' ? VCS_MODE_LABELS.git : VCS_MODE_LABELS.builtin);

  return (
    <div className="space-y-3">
      {/* 所有类型都显示约束摘要 */}
      <ConstraintSummaryWidget projectId={project.id} projectType={projectType} />

      {/* 所有类型都显示里程碑进度 */}
      <MilestoneProgressWidget projectId={project.id} projectType={projectType} />

      {/* 多态项目阶段与版本保护摘要 */}
      <div
        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-xs"
        data-testid="workspace-vcs-summary-widget"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-primary" />
          <span className="font-medium text-foreground">当前生命周期阶段：{stageLabel}</span>
          {hasSageMd !== null && (
            <span
              className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-ui-2xs font-medium ${
                hasSageMd
                  ? 'bg-emerald-500/10 text-emerald-600'
                  : 'bg-amber-500/10 text-amber-600'
              }`}
              data-testid="workspace-charter-status-badge"
            >
              <FileText className="h-2.5 w-2.5" />
              {hasSageMd ? 'L1 SAGE.md 已就绪' : 'L1 SAGE.md 待初始化'}
            </span>
          )}
          {totalFiles !== null && (
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-ui-2xs text-muted-foreground">
              {totalFiles} 个文件
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
          <History className="h-3.5 w-3.5 text-emerald-500" />
          <span>{vcsLabel}</span>
          {checkpointCount > 0 && (
            <span
              className="rounded bg-emerald-500/10 px-1.5 py-0.5 font-mono text-ui-2xs text-emerald-600"
              data-testid="workspace-vcs-checkpoint-count"
            >
              {checkpointCount} 个快照
            </span>
          )}
          <button
            type="button"
            disabled={creatingSnapshot}
            onClick={() => void handleQuickCheckpoint()}
            data-testid="overview-quick-checkpoint-btn"
            className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/5 px-2 py-0.5 text-ui-2xs font-medium text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-50"
          >
            <Plus className="h-2.5 w-2.5" />
            {creatingSnapshot ? '留痕中...' : '快捷快照'}
          </button>
        </div>
      </div>

      {/* M3: AI 项目健康顾问卡片 */}
      <ProjectAdvisorCard projectId={project.id} />

      {/* Coding 或显式启用 Git 的项目显示 Git 状态与 M5 代码→Wiki 生成面板 */}
      {(projectType === 'coding' || project.vcsMode === 'git') && (
        <GitStatusWidget projectId={project.id} />
      )}
      {projectType === 'coding' && <WikiGenerationPanel projectId={project.id} />}
    </div>
  );
}
