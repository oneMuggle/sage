import { useState } from 'react';

import { PlaybookCard } from '../../../features/playbook/PlaybookCard';
import {
  MilestoneManager,
  MilestoneProgressWidget,
  PolymorphicArchetypeCards,
  TaskDecomposeDialog,
} from '../../../features/project-type';
import { getArchetypeBlueprint } from '../../../features/project-type/archetypeBlueprints';
import { projectApi, type ProjectSummary, type ProjectType } from '../../../shared/api';
import { Button } from '../../../shared/ui/Button';
import type { GovernanceData } from '../useGovernanceProject';

export interface OverviewSectionProps {
  data: GovernanceData;
  onStartSession: () => void;
  onChangeTab: (tab: string) => void;
}

interface BootstrapStepsProps {
  steps: GovernanceData['bootstrapProgress']['steps'];
}

function BootstrapSteps({ steps }: BootstrapStepsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-ui-2xs">
      {steps.map((step) => (
        <span key={step.id} className={step.done ? 'text-emerald-600' : 'text-muted-foreground'}>
          {step.done ? '✓' : '○'} {step.label}
        </span>
      ))}
    </div>
  );
}

interface StatusCardProps {
  data: GovernanceData;
  blueprintLabel: string;
  stageLabel: string;
  bootstrapComplete: boolean;
  onStartSession: () => void;
  onChangeTab: (tab: string) => void;
}

function StatusCard({
  data,
  blueprintLabel,
  stageLabel,
  bootstrapComplete,
  onStartSession,
  onChangeTab,
}: StatusCardProps) {
  const onPrimary = () => (bootstrapComplete ? onStartSession() : onChangeTab('settings'));

  return (
    <div
      className="space-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="project-home-summary"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">项目状态</div>
          <div className="flex flex-wrap items-center gap-2 text-ui-2xs text-muted-foreground">
            <span>类型：{blueprintLabel}</span>
            <span>当前阶段：{stageLabel}</span>
            <span>
              初始化进度：{data.bootstrapProgress.done}/{data.bootstrapProgress.total}
            </span>
          </div>
        </div>
        <Button
          size="sm"
          onClick={onPrimary}
          disabled={data.startingSession}
          data-testid="project-home-cta"
        >
          {bootstrapComplete ? (data.startingSession ? '正在打开…' : '开始会话') : '继续初始化'}
        </Button>
      </div>
      {!bootstrapComplete && <BootstrapSteps steps={data.bootstrapProgress.steps} />}
    </div>
  );
}

interface StageSectionProps {
  projectId: string;
  projectType: ProjectType;
  onDecompose: () => void;
}

function StageSection({ projectId, projectType, onDecompose }: StageSectionProps) {
  return (
    <div className="space-y-2" data-testid="project-current-stage-section">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold text-foreground">当前阶段</div>
        <Button
          size="sm"
          variant="secondary"
          onClick={onDecompose}
          data-testid="project-current-stage-decompose"
        >
          AI 拆解当前阶段
        </Button>
      </div>
      <PlaybookCard projectId={projectId} />
      <MilestoneProgressWidget projectId={projectId} projectType={projectType} />
    </div>
  );
}

interface DomainSectionProps {
  project: ProjectSummary;
  projectType: ProjectType;
}

function DomainSection({ project, projectType }: DomainSectionProps) {
  return (
    <div className="space-y-2" data-testid="project-domain-section">
      <div className="text-xs font-semibold text-foreground">
        {projectType === 'coding' ? '工程概览' : '项目快览'}
      </div>
      <PolymorphicArchetypeCards project={project} projectType={projectType} />
    </div>
  );
}

interface MilestonesDisclosureProps {
  projectId: string;
  projectType: ProjectType;
}

function MilestonesDisclosure({ projectId, projectType }: MilestonesDisclosureProps) {
  return (
    <details className="rounded-lg border border-border bg-card/50">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
        里程碑（可选）
      </summary>
      <div className="px-3 pb-3">
        <MilestoneManager projectId={projectId} projectType={projectType} />
      </div>
    </details>
  );
}

function useDecomposeFlow(data: GovernanceData) {
  const [isOpen, setIsOpen] = useState(false);
  const [requirement, setRequirement] = useState('');
  const [context, setContext] = useState('');

  const open = (req: string, ctx: string) => {
    setRequirement(req);
    setContext(ctx);
    setIsOpen(true);
  };

  const onApplied = () => {
    const projectId = data.project?.id;
    if (!projectId) return;
    void projectApi
      .listMilestones(projectId)
      .then(() => data.reloadMilestones())
      .catch(() => undefined);
  };

  return { isOpen, setIsOpen, requirement, context, open, onApplied };
}

export function OverviewSection({ data, onStartSession, onChangeTab }: OverviewSectionProps) {
  const decompose = useDecomposeFlow(data);
  if (!data.project) return null;

  const project = data.project;
  const blueprint = getArchetypeBlueprint(data.activeProjectType);
  const stageLabel =
    blueprint.stages.find((stage) => stage.id === project.projectStage)?.label ?? '未设置';
  const bootstrapComplete = data.bootstrapProgress.done === data.bootstrapProgress.total;

  return (
    <div className="space-y-4">
      <StatusCard
        data={data}
        blueprintLabel={blueprint.label}
        stageLabel={stageLabel}
        bootstrapComplete={bootstrapComplete}
        onStartSession={onStartSession}
        onChangeTab={onChangeTab}
      />
      <StageSection
        projectId={project.id}
        projectType={data.activeProjectType}
        onDecompose={() =>
          decompose.open(`完成「${stageLabel}」阶段核心交付与核查`, `项目类型：${blueprint.label}`)
        }
      />
      <DomainSection project={project} projectType={data.activeProjectType} />
      <MilestonesDisclosure projectId={project.id} projectType={data.activeProjectType} />
      <TaskDecomposeDialog
        open={decompose.isOpen}
        onOpenChange={decompose.setIsOpen}
        projectId={project.id}
        projectType={data.activeProjectType}
        initialRequirement={decompose.requirement}
        initialContext={decompose.context}
        onApplied={decompose.onApplied}
      />
    </div>
  );
}
