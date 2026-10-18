/**
 * 多形态项目组织蓝图工作台 (2026-10-10；2026-10-18 Scheme 1 重构)
 *
 * 方案 1（分层渐进式披露）后：
 *   Card 1（蓝图总览）+ 形态切换 + 当前选中形态的三维组织详情 +
 *   「进入治理」按钮（跳转 /projects/governance/:projectId）。
 *
 * 原 Card 2 的 7 个治理 Tab 已迁移至 /projects/governance/:projectId。
 */

import {
  Code2,
  Briefcase,
  FlaskConical,
  User,
  Sparkles,
  FolderPlus,
  ArrowRight,
} from 'lucide-react';
import { type ComponentType } from 'react';
import { useNavigate } from 'react-router-dom';

import { type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

import { ProjectCreationWizard } from './ProjectCreationWizard';
import { ProjectOverviewWidgets } from './ProjectOverviewWidgets';
import { ProjectTypeBadge } from './ProjectTypeBadge';
import { PolymorphicArchetypeCards } from './PolymorphicArchetypeCards';
import { useStudioState } from './useStudioState';
import { ARCHETYPE_BLUEPRINTS, ARCHETYPE_ORDER } from './archetypeBlueprints';

const ARCHETYPE_ICONS: Record<ProjectType, ComponentType<{ className?: string }>> = {
  coding: Code2,
  business: Briefcase,
  research: FlaskConical,
  personal: User,
};

export interface ProjectArchetypeStudioProps {
  className?: string;
}

export function ProjectArchetypeStudio({ className }: ProjectArchetypeStudioProps) {
  const navigate = useNavigate();
  const { activeProject, selectedArchetype, setSelectedArchetype, wizardOpen, setWizardOpen } =
    useStudioState();

  const blueprint = ARCHETYPE_BLUEPRINTS[selectedArchetype];

  return (
    <div className={`space-y-4 ${className ?? ''}`} data-testid="project-archetype-studio">
      {/* 1. 多项目形态组织蓝图总览卡 */}
      <Card className="p-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">
                多形态项目组织规范总览（代码工程 · 一般档案 · 科学研究 · 个人空间）
              </h2>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              不同类型项目拥有差异化的推荐目录结构、版本控制策略、AI 上下文注入重点与阶段推进管线
            </p>
          </div>

          <Button
            size="sm"
            onClick={() => setWizardOpen(true)}
            data-testid="project-wizard-open-btn"
          >
            <FolderPlus className="mr-1.5 h-4 w-4" />
            向导新建项目
          </Button>
        </div>

        {/* 四大形态切换标签 */}
        <div
          className="grid grid-cols-2 gap-2 md:grid-cols-4"
          data-testid="archetype-blueprint-tabs"
        >
          {ARCHETYPE_ORDER.map((typeKey) => {
            const meta = ARCHETYPE_BLUEPRINTS[typeKey];
            const Icon = ARCHETYPE_ICONS[typeKey];
            const isSelected = selectedArchetype === typeKey;
            return (
              <button
                key={typeKey}
                type="button"
                onClick={() => setSelectedArchetype(typeKey)}
                data-testid={`archetype-tab-${typeKey}`}
                className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all ${
                  isSelected
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border bg-card hover:border-primary/40 hover:bg-muted/30'
                }`}
              >
                <div className="flex w-full items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground">
                    <Icon className="h-3.5 w-3.5 text-primary" />
                    {meta.label}
                  </span>
                  <ProjectTypeBadge type={typeKey} />
                </div>
                <span className="text-ui-2xs text-muted-foreground line-clamp-1">
                  {meta.englishLabel}
                </span>
              </button>
            );
          })}
        </div>

        {/* 当前选中形态的三维组织详情 */}
        <div
          className="grid gap-3 rounded-lg border border-border/80 bg-muted/20 p-3.5 lg:grid-cols-3"
          data-testid={`archetype-blueprint-detail-${blueprint.type}`}
        >
          <div className="space-y-2">
            <div className="text-xs font-semibold text-foreground">1. 标准工作区目录结构 & VCS</div>
            <p className="text-xs text-muted-foreground">{blueprint.positioning}</p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {blueprint.directories.map((dir) => (
                <span
                  key={dir}
                  className="rounded border border-border bg-background px-2 py-0.5 font-mono text-xs text-foreground"
                >
                  {dir}/
                </span>
              ))}
              <span className="rounded border border-primary/40 bg-background px-2 py-0.5 font-mono text-xs text-primary">
                SAGE.md
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              版本控制：<span className="font-medium text-foreground">{blueprint.vcsLabel}</span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold text-foreground">2. 五层上下文注入与护栏重点</div>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {blueprint.contextPillars.map((pillar, idx) => (
                <li key={idx} className="flex items-start gap-1.5">
                  <span className="mt-0.5 text-primary">•</span>
                  <span>{pillar}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold text-foreground">3. 阶段推进管线与预设规则包</div>
            <div className="flex flex-wrap items-center gap-1.5">
              {blueprint.stages.map((st, idx) => (
                <span
                  key={st.id}
                  title={st.hint}
                  className="inline-flex items-center gap-1 rounded bg-background px-2 py-0.5 text-xs text-foreground border border-border"
                >
                  <span className="text-muted-foreground">{idx + 1}.</span>
                  {st.label}
                </span>
              ))}
            </div>
            {blueprint.subTemplates.length > 0 && (
              <div className="pt-1 space-y-1">
                <div className="text-xs text-muted-foreground">内置细分约束模板：</div>
                <div className="flex flex-wrap gap-1.5">
                  {blueprint.subTemplates.map((tpl) => (
                    <span
                      key={tpl.key}
                      className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                    >
                      {tpl.label}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* 2. 活跃项目态势概览 + 进入治理 */}
      {activeProject && (
        <Card className="p-4 space-y-4" data-testid="studio-active-project-overview">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-xs font-medium text-muted-foreground">当前项目：</span>
              <span className="text-sm font-semibold text-foreground">{activeProject.name}</span>
              <ProjectTypeBadge
                type={activeProject.projectType ?? activeProject.detectedType}
                detected={!activeProject.projectType && Boolean(activeProject.detectedType)}
              />
              <span className="text-xs text-muted-foreground font-mono">{activeProject.path}</span>
            </div>
            <Button
              size="sm"
              onClick={() => navigate(`/projects/governance/${activeProject.id}`)}
              data-testid="enter-governance-btn"
            >
              进入治理
              <ArrowRight className="ml-1.5 h-4 w-4" />
            </Button>
          </div>

          {/* 态势卡片：多形态类型卡 + Git/约束/里程碑/资料概览 */}
          <PolymorphicArchetypeCards
            project={activeProject}
            projectType={
              (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
            }
          />
          <ProjectOverviewWidgets project={activeProject} />
        </Card>
      )}

      {/* 项目创建三步向导弹窗 */}
      <ProjectCreationWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onSuccess={(created) => {
          if (created.projectType) {
            setSelectedArchetype(created.projectType);
          }
        }}
      />
    </div>
  );
}
