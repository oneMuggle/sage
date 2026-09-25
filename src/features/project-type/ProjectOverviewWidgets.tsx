/**
 * 项目概览 Widget (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.3
 * 根据项目类型显示不同的概览 Widget
 */

import type { ProjectSummary } from '../../shared/api';

import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
import { GitStatusWidget } from './GitStatusWidget';
import { MilestoneProgressWidget } from './MilestoneProgressWidget';

export interface ProjectOverviewWidgetsProps {
  project: ProjectSummary;
}

export function ProjectOverviewWidgets({ project }: ProjectOverviewWidgetsProps) {
  const projectType = project.projectType;

  return (
    <div className="space-y-3">
      {/* 所有类型都显示约束摘要 */}
      <ConstraintSummaryWidget projectId={project.id} projectType={projectType} />

      {/* 所有类型都显示里程碑进度 */}
      <MilestoneProgressWidget projectId={project.id} />

      {/* Coding 项目显示 Git 状态 */}
      {projectType === 'coding' && <GitStatusWidget projectId={project.id} />}
    </div>
  );
}
