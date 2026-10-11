/**
 * 项目概览 Widget (2026-09-25; Phase P14 多态版本保护与阶段状态卡片 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.3
 * 根据项目类型与版本控制策略显示对应的概览 Widget
 */

import { History, Layers } from 'lucide-react';
import { useEffect, useState } from 'react';

import { projectApi, type ProjectSummary } from '../../shared/api';

import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
import { GitStatusWidget } from './GitStatusWidget';
import { MilestoneProgressWidget } from './MilestoneProgressWidget';
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

  useEffect(() => {
    if (!project.id || typeof projectApi?.getWorkspaceOverview !== 'function') return;
    let active = true;
    projectApi
      .getWorkspaceOverview(project.id)
      .then((ov) => {
        if (active) {
          setCheckpointCount(ov.recentCheckpoints?.length ?? 0);
        }
      })
      .catch(() => {
        if (active) setCheckpointCount(0);
      });
    return () => {
      active = false;
    };
  }, [project.id]);

  const stageLabel =
    blueprint.stages.find((s) => s.id === project.projectStage)?.label ??
    project.projectStage ??
    blueprint.stages[0]?.label ??
    '默认阶段';

  const vcsLabel =
    VCS_MODE_LABELS[project.vcsMode ?? ''] ??
    (projectType === 'coding' ? VCS_MODE_LABELS.git : VCS_MODE_LABELS.builtin);

  return (
    <div className="space-y-3">
      {/* 所有类型都显示约束摘要 */}
      <ConstraintSummaryWidget projectId={project.id} projectType={projectType} />

      {/* 所有类型都显示里程碑进度 */}
      <MilestoneProgressWidget projectId={project.id} />

      {/* 多态项目阶段与版本保护摘要 */}
      <div
        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-xs"
        data-testid="workspace-vcs-summary-widget"
      >
        <div className="flex items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-primary" />
          <span className="font-medium text-foreground">当前生命周期阶段：{stageLabel}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
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
        </div>
      </div>

      {/* Coding 或显式启用 Git 的项目显示 Git 状态 */}
      {(projectType === 'coding' || project.vcsMode === 'git') && (
        <GitStatusWidget projectId={project.id} />
      )}
    </div>
  );
}
