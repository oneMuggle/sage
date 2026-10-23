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
import { type ComponentType, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { projectApi, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

import { PolymorphicArchetypeCards } from './PolymorphicArchetypeCards';
import { ProjectCreationWizard } from './ProjectCreationWizard';
import { ProjectOverviewWidgets } from './ProjectOverviewWidgets';
import { ProjectTypeBadge } from './ProjectTypeBadge';
import { ARCHETYPE_BLUEPRINTS, ARCHETYPE_ORDER } from './archetypeBlueprints';
import { useStudioState } from './useStudioState';

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
  const [copiedActivePath, setCopiedActivePath] = useState(false);
  const [savedBlueprintL4, setSavedBlueprintL4] = useState(false);
  const [savedBlueprintL3, setSavedBlueprintL3] = useState(false);
  const [scaffolded, setScaffolded] = useState(false);
  const [seededMilestones, setSeededMilestones] = useState(false);
  const [convertedBlueprintL2, setConvertedBlueprintL2] = useState(false);
  const [copiedVcs, setCopiedVcs] = useState(false);
  const [createdBlueprintMs, setCreatedBlueprintMs] = useState(false);
  const [copiedPositioning, setCopiedPositioning] = useState(false);

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

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => setWizardOpen(true)}
              data-testid="project-wizard-open-btn"
            >
              <FolderPlus className="mr-1.5 h-4 w-4" />
              向导新建项目
            </Button>
          </div>
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
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-foreground">1. 标准工作区目录结构 & VCS</div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  data-testid="studio-copy-vcs-btn"
                  onClick={async () => {
                    try {
                      await navigator.clipboard?.writeText(blueprint.vcsLabel);
                      setCopiedVcs(true);
                      setTimeout(() => setCopiedVcs(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedVcs ? '已复制VCS' : '复制 VCS 策略'}
                </button>
                <button
                  type="button"
                  data-testid="studio-copy-positioning-btn"
                  onClick={async () => {
                    setCopiedPositioning(true);
                    setTimeout(() => setCopiedPositioning(false), 1500);
                    try {
                      await navigator.clipboard?.writeText(blueprint.positioning);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedPositioning ? '已复制定位' : '复制定位'}
                </button>
              </div>
            </div>
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
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-foreground">2. 五层上下文注入与护栏重点</div>
            </div>
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
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-foreground">3. 阶段推进管线与预设规则包</div>
              <div className="flex items-center gap-1">
              </div>
            </div>
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
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="studio-copy-active-path-btn"
                onClick={async () => {
                  try {
                    await navigator.clipboard?.writeText(activeProject.path);
                    setCopiedActivePath(true);
                    setTimeout(() => setCopiedActivePath(false), 1500);
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {copiedActivePath ? '已复制路径' : '复制项目路径'}
              </button>
              <button
                type="button"
                data-testid="studio-save-blueprint-l4-btn"
                onClick={async () => {
                  if (savedBlueprintL4) return;
                  setSavedBlueprintL4(true);
                  if (typeof projectApi?.addMaterial === 'function') {
                    const bp =
                      ARCHETYPE_BLUEPRINTS[
                        (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
                      ];
                    const md = [
                      `# ${bp.label} 组织规范蓝图 (${activeProject.name})`,
                      `- 工作区定位：${bp.positioning}`,
                      `- 标准目录：${bp.directories.map((d) => `${d}/`).join(' · ')}`,
                      `- 版本控制：${bp.vcsLabel}`,
                      `- 阶段管线：${bp.stages.map((s) => s.label).join(' → ')}`,
                    ].join('\n');
                    try {
                      await projectApi.addMaterial(activeProject.id, { content: md });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {savedBlueprintL4 ? '已存蓝图 L4' : '当前蓝图存 L4'}
              </button>
              <button
                type="button"
                data-testid="studio-save-blueprint-l3-btn"
                onClick={async () => {
                  if (savedBlueprintL3) return;
                  setSavedBlueprintL3(true);
                  if (typeof projectApi?.confirmKnowledge === 'function') {
                    const bp =
                      ARCHETYPE_BLUEPRINTS[
                        (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
                      ];
                    try {
                      await projectApi.confirmKnowledge(activeProject.id, {
                        entries: [
                          {
                            category: 'architecture',
                            content: `${bp.label} 蓝图规范 (${activeProject.name})：目录=${bp.directories.join('/, ')}/；阶段=${bp.stages.map((s) => s.label).join('→')}`,
                            importance: 8,
                            sourceMessageIds: [],
                            reasoning: '多形态蓝图工作台一键沉淀当前蓝图至 L3 画像',
                          },
                        ],
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {savedBlueprintL3 ? '已存蓝图 L3' : '当前蓝图存 L3'}
              </button>
              <button
                type="button"
                data-testid="studio-quick-scaffold-btn"
                onClick={async () => {
                  if (scaffolded) return;
                  setScaffolded(true);
                  if (typeof projectApi?.scaffold === 'function') {
                    try {
                      await projectApi.scaffold(activeProject.id, {
                        projectType: (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType,
                        createDirectories: true,
                        createSageMd: true,
                        importDefaultConstraints: true,
                        seedDefaultMilestones: true,
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {scaffolded ? '已初始化脚手架' : '一键脚手架初始化'}
              </button>
              <button
                type="button"
                data-testid="studio-seed-recommended-milestones-btn"
                onClick={async () => {
                  if (seededMilestones) return;
                  setSeededMilestones(true);
                  if (typeof projectApi?.createMilestone === 'function') {
                    const bp =
                      ARCHETYPE_BLUEPRINTS[
                        (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
                      ];
                    let order = 0;
                    for (const m of bp.recommendedMilestones) {
                      try {
                        await projectApi.createMilestone(activeProject.id, {
                          title: m.title,
                          description: m.description,
                          stage: m.stage,
                          sortOrder: order++,
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {seededMilestones ? '已播种里程碑' : '一键播种推荐里程碑'}
              </button>
              <button
                type="button"
                data-testid="studio-blueprint-to-constraint-btn"
                onClick={async () => {
                  if (convertedBlueprintL2) return;
                  setConvertedBlueprintL2(true);
                  if (typeof projectApi?.createConstraint === 'function') {
                    const bp =
                      ARCHETYPE_BLUEPRINTS[
                        (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
                      ];
                    try {
                      await projectApi.createConstraint(activeProject.id, {
                        category: 'archetype_blueprint',
                        content: `[${bp.label}蓝图护栏] 标准目录：${bp.directories.join('、')} · 版本控制：${bp.vcsLabel}`,
                        triggerPattern: 'always',
                        priority: 8,
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {convertedBlueprintL2 ? '已转蓝图L2' : '当前蓝图转L2'}
              </button>
              <button
                type="button"
                data-testid="studio-blueprint-to-milestone-btn"
                onClick={async () => {
                  if (createdBlueprintMs) return;
                  setCreatedBlueprintMs(true);
                  if (typeof projectApi?.createMilestone === 'function') {
                    const bp =
                      ARCHETYPE_BLUEPRINTS[
                        (activeProject.projectType ?? activeProject.detectedType ?? 'business') as ProjectType
                      ];
                    try {
                      await projectApi.createMilestone(activeProject.id, {
                        title: `[${bp.label}蓝图验收] ${activeProject.name} 规范落地核查`,
                        description: `目录：${bp.directories.join('、')} · 阶段：${bp.stages.map((s) => s.label).join('→')}`,
                        status: 'pending',
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
              >
                {createdBlueprintMs ? '已建蓝图里程碑' : '当前蓝图建里程碑'}
              </button>
              <Button
                size="sm"
                onClick={() => navigate(`/projects/governance/${activeProject.id}`)}
                data-testid="enter-governance-btn"
              >
                进入治理
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Button>
            </div>
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
