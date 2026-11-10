import { AlertCircle, ArrowRight, CheckCircle2, Circle, CircleDot } from 'lucide-react';
import { useMemo, useState } from 'react';

import { PlaybookCard } from '../../../features/playbook/PlaybookCard';
import {
  GitStatusWidget,
  MilestoneManager,
  MilestoneProgressWidget,
  PolymorphicArchetypeCards,
  TaskDecomposeDialog,
} from '../../../features/project-type';
import { getArchetypeBlueprint } from '../../../features/project-type/archetypeBlueprints';
import { projectApi, type ProjectSummary, type ProjectType } from '../../../shared/api';
import { Button } from '../../../shared/ui/Button';
import { Progress } from '../../../shared/ui/Progress';
import type { GovernanceData } from '../useGovernanceProject';

export interface OverviewSectionProps {
  data: GovernanceData;
  onStartSession: () => void;
  onChangeTab: (tab: string) => void;
}

interface StatusCardProps {
  data: GovernanceData;
  blueprintLabel: string;
  stageLabel: string;
  bootstrapComplete: boolean;
  onChangeTab: (tab: string) => void;
}

function StatusCard({
  data,
  blueprintLabel,
  stageLabel,
  bootstrapComplete,
  onChangeTab,
}: StatusCardProps) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3"
      data-testid="project-home-summary"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>
          类型：<span className="font-medium text-foreground">{blueprintLabel}</span>
        </span>
        <span>
          当前阶段：<span className="font-medium text-foreground">{stageLabel}</span>
        </span>
        <span>
          初始化：
          <span className="font-medium text-foreground">
            {data.bootstrapProgress.done}/{data.bootstrapProgress.total}
          </span>
        </span>
      </div>
      {/* 主 CTA 常驻页面头部；此处只在未初始化时给出上下文操作 */}
      {bootstrapComplete ? null : (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onChangeTab('settings')}
          data-testid="project-home-cta"
        >
          继续初始化
        </Button>
      )}
    </div>
  );
}

interface NextAction {
  id: string;
  title: string;
  hint: string;
  actionLabel: string;
  onAction: () => void;
}

interface NextActionsCardProps {
  actions: NextAction[];
  onStartSession: () => void;
}

function NextActionsCard({ actions, onStartSession }: NextActionsCardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-4" data-testid="project-next-actions">
      <div className="mb-2 text-sm font-semibold text-foreground">下一步</div>
      {actions.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">一切就绪，可以开始工作了。</span>
          <Button size="sm" variant="secondary" onClick={onStartSession}>
            开始会话
          </Button>
        </div>
      ) : (
        <ul className="space-y-1.5">
          {actions.map((action) => (
            <li
              key={action.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/30 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="text-xs font-medium text-foreground">{action.title}</div>
                <div className="text-ui-2xs text-muted-foreground">{action.hint}</div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={action.onAction}
                data-testid={`project-next-action-${action.id}`}
              >
                {action.actionLabel}
                <ArrowRight className="ml-1 h-3 w-3" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function useMilestoneCounts(milestones: GovernanceData['milestones']) {
  return useMemo(() => {
    const completed = milestones.filter((item) => item.status === 'completed').length;
    const blocked = milestones.filter((item) => item.status === 'blocked').length;
    const inProgress = milestones.filter((item) => item.status === 'in_progress').length;
    const total = milestones.length;
    return {
      total,
      completed,
      blocked,
      inProgress,
      open: total - completed,
      progress: total > 0 ? Math.round((completed / total) * 100) : 0,
      recent: milestones
        .filter((item) => item.status !== 'completed')
        .sort((a, b) => String(a.dueDate ?? '').localeCompare(String(b.dueDate ?? '')))
        .slice(0, 3),
    };
  }, [milestones]);
}

function MilestoneStatusIcon({ status }: { status: string }) {
  if (status === 'blocked') {
    return <AlertCircle className="h-3 w-3 shrink-0 text-amber-500" aria-hidden="true" />;
  }
  if (status === 'in_progress') {
    return <CircleDot className="h-3 w-3 shrink-0 text-primary" aria-hidden="true" />;
  }
  return <Circle className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />;
}

interface MilestoneSummaryProps {
  counts: ReturnType<typeof useMilestoneCounts>;
  projectId: string;
  projectType: ProjectType;
}

function MilestoneSummary({ counts, projectId, projectType }: MilestoneSummaryProps) {
  return (
    <div
      id="project-milestones"
      className="space-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="project-milestone-summary"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <CheckCircle2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          里程碑进度
        </div>
        <span className="text-xs text-muted-foreground">
          {counts.completed} / {counts.total}
        </span>
      </div>

      {counts.total === 0 ? (
        <p className="text-xs text-muted-foreground">还没有里程碑。可让 AI 拆解当前阶段生成。</p>
      ) : (
        <>
          <Progress value={counts.progress} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-ui-2xs text-muted-foreground">
            <span>完成 {counts.completed}</span>
            <span>进行中 {counts.inProgress}</span>
            <span>阻塞 {counts.blocked}</span>
            <span className="ml-auto">{counts.progress}%</span>
          </div>
          {counts.recent.length > 0 && (
            <ul className="space-y-1">
              {counts.recent.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center gap-2 text-xs text-text-secondary"
                  data-testid="project-milestone-recent"
                >
                  <MilestoneStatusIcon status={item.status} />
                  <span className="truncate">{item.title}</span>
                  {item.dueDate && (
                    <span className="ml-auto shrink-0 text-ui-2xs text-muted-foreground">
                      {item.dueDate}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <details className="rounded-md border border-border/60 bg-card/50">
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
          管理全部里程碑
        </summary>
        <div className="space-y-3 px-3 pb-3">
          <MilestoneProgressWidget projectId={projectId} projectType={projectType} />
          <MilestoneManager projectId={projectId} projectType={projectType} />
        </div>
      </details>
    </div>
  );
}

interface StageSectionProps {
  projectId: string;
  onDecompose: () => void;
}

function StageSection({ projectId, onDecompose }: StageSectionProps) {
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
      <PlaybookCard projectId={projectId} compact />
    </div>
  );
}

interface ProjectStructureProps {
  project: ProjectSummary;
  projectType: ProjectType;
}

function ProjectStructure({ project, projectType }: ProjectStructureProps) {
  return (
    <details className="rounded-lg border border-border bg-card/50" data-testid="project-structure">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
        项目结构（工程概览 · Git 状态）
      </summary>
      <div className="space-y-3 px-3 pb-3">
        <PolymorphicArchetypeCards project={project} projectType={projectType} />
        <GitStatusWidget projectId={project.id} />
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
  const counts = useMilestoneCounts(data.milestones);
  if (!data.project) return null;

  const project = data.project;
  const blueprint = getArchetypeBlueprint(data.activeProjectType);
  const stageLabel =
    blueprint.stages.find((stage) => stage.id === project.projectStage)?.label ?? '未设置';
  const bootstrapComplete = data.bootstrapProgress.done === data.bootstrapProgress.total;
  const scrollToMilestones = () =>
    document
      .getElementById('project-milestones')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const openDecompose = () =>
    decompose.open(`完成「${stageLabel}」阶段核心交付与核查`, `项目类型：${blueprint.label}`);

  const actions: NextAction[] = [];
  if (!bootstrapComplete) {
    actions.push({
      id: 'bootstrap',
      title: `完成项目初始化（${data.bootstrapProgress.done}/${data.bootstrapProgress.total}）`,
      hint: '补齐项目说明、规则与里程碑，让 AI 更了解这个项目',
      actionLabel: '继续初始化',
      onAction: () => onChangeTab('settings'),
    });
  }
  if (counts.open > 0) {
    actions.push({
      id: 'milestones',
      title: `完成 ${counts.open} 个里程碑`,
      hint: '当前阶段还有未完成事项',
      actionLabel: '查看',
      onAction: scrollToMilestones,
    });
  } else if (counts.total === 0) {
    actions.push({
      id: 'decompose',
      title: '还没有里程碑',
      hint: '让 AI 按当前阶段拆解成可执行任务',
      actionLabel: 'AI 拆解',
      onAction: openDecompose,
    });
  }
  if (data.upcomingDeadline) {
    const { title, daysLeft } = data.upcomingDeadline;
    actions.push({
      id: 'deadline',
      title: daysLeft < 0 ? `已逾期：${title}` : `${title} · ${daysLeft} 天后截止`,
      hint: '最近的项目节点',
      actionLabel: '查看',
      onAction: scrollToMilestones,
    });
  }

  return (
    <div className="space-y-4">
      <StatusCard
        data={data}
        blueprintLabel={blueprint.label}
        stageLabel={stageLabel}
        bootstrapComplete={bootstrapComplete}
        onChangeTab={onChangeTab}
      />
      <NextActionsCard actions={actions.slice(0, 3)} onStartSession={onStartSession} />
      <MilestoneSummary
        counts={counts}
        projectId={project.id}
        projectType={data.activeProjectType}
      />
      <StageSection projectId={project.id} onDecompose={openDecompose} />
      <ProjectStructure project={project} projectType={data.activeProjectType} />
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
