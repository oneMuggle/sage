import { useState } from 'react';

import { PlaybookCard } from '../../../features/playbook/PlaybookCard';
import {
  MilestoneManager,
  MilestoneProgressWidget,
  PolymorphicArchetypeCards,
  TaskDecomposeDialog,
} from '../../../features/project-type';
import { getArchetypeBlueprint } from '../../../features/project-type/archetypeBlueprints';
import { projectApi } from '../../../shared/api';
import { Button } from '../../../shared/ui/Button';
import type { GovernanceData } from '../useGovernanceProject';

export interface OverviewSectionProps {
  data: GovernanceData;
  onStartSession: () => void;
  onChangeTab: (tab: string) => void;
}

export function OverviewSection({ data, onStartSession, onChangeTab }: OverviewSectionProps) {
  const [decomposeOpen, setDecomposeOpen] = useState(false);
  const [decomposeReq, setDecomposeReq] = useState('');
  const [decomposeCtx, setDecomposeCtx] = useState('');
  if (!data.project) return null;

  const project = data.project;
  const blueprint = getArchetypeBlueprint(data.activeProjectType);
  const stageLabel =
    blueprint.stages.find((stage) => stage.id === project.projectStage)?.label ?? '未设置';
  const bootstrapComplete = data.bootstrapProgress.done === data.bootstrapProgress.total;

  return (
    <div className="space-y-4">
      <div
        className="space-y-3 rounded-lg border border-border bg-card p-4"
        data-testid="project-home-summary"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="text-sm font-semibold text-foreground">项目状态</div>
            <div className="flex flex-wrap items-center gap-2 text-ui-2xs text-muted-foreground">
              <span>类型：{blueprint.label}</span>
              <span>当前阶段：{stageLabel}</span>
              <span>
                初始化进度：{data.bootstrapProgress.done}/{data.bootstrapProgress.total}
              </span>
            </div>
          </div>
          <Button
            size="sm"
            onClick={() => (bootstrapComplete ? onStartSession() : onChangeTab('settings'))}
            disabled={data.startingSession}
            data-testid="project-home-cta"
          >
            {bootstrapComplete ? (data.startingSession ? '正在打开…' : '开始会话') : '继续初始化'}
          </Button>
        </div>
        {!bootstrapComplete && (
          <div className="flex flex-wrap items-center gap-2 text-ui-2xs">
            {data.bootstrapProgress.steps.map((step) => (
              <span
                key={step.id}
                className={step.done ? 'text-emerald-600' : 'text-muted-foreground'}
              >
                {step.done ? '✓' : '○'} {step.label}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2" data-testid="project-current-stage-section">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-semibold text-foreground">当前阶段</div>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setDecomposeReq(`完成「${stageLabel}」阶段核心交付与核查`);
              setDecomposeCtx(`项目类型：${blueprint.label}`);
              setDecomposeOpen(true);
            }}
            data-testid="project-current-stage-decompose"
          >
            AI 拆解当前阶段
          </Button>
        </div>
        <PlaybookCard projectId={project.id} />
        <MilestoneProgressWidget projectId={project.id} projectType={data.activeProjectType} />
      </div>

      <div className="space-y-2" data-testid="project-domain-section">
        <div className="text-xs font-semibold text-foreground">
          {data.activeProjectType === 'coding' ? '工程概览' : '项目快览'}
        </div>
        <PolymorphicArchetypeCards project={project} projectType={data.activeProjectType} />
      </div>

      <details className="rounded-lg border border-border bg-card/50">
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
          里程碑（可选）
        </summary>
        <div className="px-3 pb-3">
          <MilestoneManager projectId={project.id} projectType={data.activeProjectType} />
        </div>
      </details>

      <TaskDecomposeDialog
        open={decomposeOpen}
        onOpenChange={setDecomposeOpen}
        projectId={project.id}
        projectType={data.activeProjectType}
        initialRequirement={decomposeReq}
        initialContext={decomposeCtx}
        onApplied={() => {
          void projectApi
            .listMilestones(project.id)
            .then(() => data.reloadMilestones())
            .catch(() => undefined);
        }}
      />
    </div>
  );
}
