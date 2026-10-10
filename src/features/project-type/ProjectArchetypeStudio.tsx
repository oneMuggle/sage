/**
 * 多形态项目组织与治理工作台面板 (2026-10-10)
 *
 * 将代码工程项目 (coding)、一般档案项目 (business)、科学研究项目 (research) 与个人知识空间 (personal)
 * 的三层架构（组织蓝图预览 + 活跃项目类型/阶段/脚手架一键初始化 + 约束/里程碑/跨目录白名单深度治理）
 * 统一挂载到 `/projects` 工作台。
 */

import {
  Code2,
  Briefcase,
  FlaskConical,
  User,
  Sparkles,
  FolderPlus,
  Layers,
  ShieldCheck,
  Target,
  FolderLock,
  CheckCircle2,
  Plus,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useState, type ComponentType } from 'react';

import {
  projectApi,
  type ProjectSummary,
  type ProjectType,
  type ProjectScaffoldResult,
} from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

import { ConstraintManager } from './ConstraintManager';
import { MilestoneManager } from './MilestoneManager';
import { ProjectCreationWizard } from './ProjectCreationWizard';
import { ProjectOverviewWidgets } from './ProjectOverviewWidgets';
import { ProjectTypeBadge } from './ProjectTypeBadge';
import {
  ARCHETYPE_BLUEPRINTS,
  ARCHETYPE_ORDER,
  getArchetypeBlueprint,
} from './archetypeBlueprints';

const ARCHETYPE_ICONS: Record<ProjectType, ComponentType<{ className?: string }>> = {
  coding: Code2,
  business: Briefcase,
  research: FlaskConical,
  personal: User,
};

type StudioTab = 'overview' | 'constraints' | 'milestones' | 'allowed_paths';

export interface ProjectArchetypeStudioProps {
  className?: string;
}

export function ProjectArchetypeStudio({ className }: ProjectArchetypeStudioProps) {
  const [selectedArchetype, setSelectedArchetype] = useState<ProjectType>('coding');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<StudioTab>('overview');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [scaffolding, setScaffolding] = useState(false);
  const [scaffoldResult, setScaffoldResult] = useState<ProjectScaffoldResult | null>(null);
  const [newAllowedPath, setNewAllowedPath] = useState('');
  const [savingPaths, setSavingPaths] = useState(false);

  const loadProjects = useCallback(async () => {
    if (typeof projectApi?.list !== 'function') return;
    try {
      const list = await projectApi.list();
      if (!Array.isArray(list)) return;
      setProjects(list);
      setSelectedProjectId((prev) => {
        if (prev && list.some((p) => p.id === prev)) return prev;
        return list[0]?.id ?? null;
      });
    } catch {
      // 测试或未连接后端时静默降级
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const activeProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const activeProjectType: ProjectType =
    (activeProject?.projectType ?? activeProject?.detectedType ?? selectedArchetype) || 'business';
  const blueprint = getArchetypeBlueprint(selectedArchetype);
  const activeBlueprint = getArchetypeBlueprint(activeProjectType);

  const handleChangeProjectType = async (nextType: ProjectType) => {
    if (!activeProject || typeof projectApi?.update !== 'function') return;
    try {
      const nextStage = getArchetypeBlueprint(nextType).stages[0]?.id ?? null;
      const updated = await projectApi.update(activeProject.id, {
        project_type: nextType,
        project_stage: nextStage,
      });
      setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setSelectedArchetype(nextType);
    } catch {
      // ignore
    }
  };

  const handleChangeProjectStage = async (nextStage: string) => {
    if (!activeProject || typeof projectApi?.update !== 'function') return;
    try {
      const updated = await projectApi.update(activeProject.id, {
        project_stage: nextStage,
      });
      setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    } catch {
      // ignore
    }
  };

  const handleScaffoldActiveProject = async () => {
    if (!activeProject || typeof projectApi?.scaffold !== 'function') return;
    setScaffolding(true);
    setScaffoldResult(null);
    try {
      const res = await projectApi.scaffold(activeProject.id, {
        projectType: activeProjectType,
        createDirectories: true,
        createSageMd: true,
        importDefaultConstraints: true,
        seedDefaultMilestones: true,
      });
      setScaffoldResult(res);
      setProjects((prev) => prev.map((p) => (p.id === res.project.id ? res.project : p)));
    } catch {
      // ignore
    } finally {
      setScaffolding(false);
    }
  };

  const handleAddAllowedPath = async () => {
    const trimmed = newAllowedPath.trim();
    if (!activeProject || !trimmed || typeof projectApi?.updateAllowedPaths !== 'function') return;
    const current = activeProject.allowedPaths ?? [];
    if (current.includes(trimmed)) {
      setNewAllowedPath('');
      return;
    }
    setSavingPaths(true);
    try {
      const next = await projectApi.updateAllowedPaths(activeProject.id, [...current, trimmed]);
      setProjects((prev) =>
        prev.map((p) => (p.id === activeProject.id ? { ...p, allowedPaths: next } : p)),
      );
      setNewAllowedPath('');
    } catch {
      // ignore
    } finally {
      setSavingPaths(false);
    }
  };

  const handleRemoveAllowedPath = async (targetPath: string) => {
    if (!activeProject || typeof projectApi?.updateAllowedPaths !== 'function') return;
    const current = activeProject.allowedPaths ?? [];
    setSavingPaths(true);
    try {
      const next = await projectApi.updateAllowedPaths(
        activeProject.id,
        current.filter((item) => item !== targetPath),
      );
      setProjects((prev) =>
        prev.map((p) => (p.id === activeProject.id ? { ...p, allowedPaths: next } : p)),
      );
    } catch {
      // ignore
    } finally {
      setSavingPaths(false);
    }
  };

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
            <div className="text-xs font-semibold text-foreground">
              1. 标准工作区目录结构 & VCS
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
            <div className="text-xs font-semibold text-foreground">
              2. 五层上下文注入与护栏重点
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
            <div className="text-xs font-semibold text-foreground">
              3. 阶段推进管线与预设规则包
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

      {/* 2. 已登记项目的深度治理工作台（激活 11 个类型化组件） */}
      {projects.length > 0 && activeProject && (
        <Card className="p-4 space-y-4" data-testid="project-governance-studio">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-xs font-medium text-muted-foreground">当前治理项目：</span>
              <select
                value={activeProject.id}
                onChange={(e) => {
                  setSelectedProjectId(e.target.value);
                  setScaffoldResult(null);
                }}
                aria-label="选择治理项目"
                className="rounded-md border border-input bg-background px-2.5 py-1 text-sm font-medium text-foreground"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.path})
                  </option>
                ))}
              </select>

              <ProjectTypeBadge
                type={activeProject.projectType ?? activeProject.detectedType}
                detected={!activeProject.projectType && Boolean(activeProject.detectedType)}
              />
            </div>

            {/* 项目形态与阶段快速切换 */}
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={activeProjectType}
                onChange={(e) => void handleChangeProjectType(e.target.value as ProjectType)}
                aria-label="切换项目形态"
                className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
              >
                {ARCHETYPE_ORDER.map((t) => (
                  <option key={t} value={t}>
                    形态：{ARCHETYPE_BLUEPRINTS[t].label}
                  </option>
                ))}
              </select>

              <select
                value={activeProject.projectStage ?? ''}
                onChange={(e) => void handleChangeProjectStage(e.target.value)}
                aria-label="切换项目阶段"
                className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
              >
                <option value="">阶段：未设置</option>
                {activeBlueprint.stages.map((st) => (
                  <option key={st.id} value={st.id}>
                    阶段：{st.label}
                  </option>
                ))}
              </select>

              <Button
                size="sm"
                variant="secondary"
                onClick={() => void handleScaffoldActiveProject()}
                disabled={scaffolding}
                data-testid="studio-scaffold-btn"
              >
                <Sparkles className="mr-1.5 h-3.5 w-3.5 text-primary" />
                {scaffolding ? '初始化中...' : '一键初始化目录与规范'}
              </Button>
            </div>
          </div>

          {scaffoldResult && (
            <div
              className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-foreground"
              data-testid="studio-scaffold-feedback"
            >
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
              <span>
                已按「{activeBlueprint.label}」完成初始化：新建目录{' '}
                {scaffoldResult.createdDirectories.length} 个、新建文件{' '}
                {scaffoldResult.createdFiles.join(', ') || '无（保留已有 SAGE.md）'}、导入约束{' '}
                {scaffoldResult.importedConstraintsCount} 条、初始化里程碑{' '}
                {scaffoldResult.seededMilestonesCount} 项。
              </span>
            </div>
          )}

          {/* 四个深度治理子面板切换 */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab('overview')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'overview'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              态势卡片 (Git / 约束 / 里程碑汇总)
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('constraints')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'constraints'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              AI 行为约束规则
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('milestones')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'milestones'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <Target className="h-3.5 w-3.5" />
              阶段与里程碑管理
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('allowed_paths')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'allowed_paths'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <FolderLock className="h-3.5 w-3.5" />
              跨目录只读白名单 ({activeProject.allowedPaths?.length ?? 0})
            </button>
          </div>

          {/* 子面板内容 */}
          {activeTab === 'overview' && <ProjectOverviewWidgets project={activeProject} />}

          {activeTab === 'constraints' && (
            <ConstraintManager projectId={activeProject.id} projectType={activeProjectType} />
          )}

          {activeTab === 'milestones' && <MilestoneManager projectId={activeProject.id} />}

          {activeTab === 'allowed_paths' && (
            <div className="space-y-3" data-testid="project-allowed-paths-panel">
              <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
                <div className="font-medium text-foreground">
                  读写非对称安全边界（Workspace Write + Allowed Paths Read-Only）
                </div>
                <p>
                  • 主工作区目录（<code className="font-mono">{activeProject.path}</code>
                  ）：允许 AI 读写文件与生成交付物。
                </p>
                <p>
                  • 跨目录只读白名单（<code className="font-mono">allowed_paths</code>
                  ）：适合挂载一般档案的「企业合同/公文范本库」、科研项目的「Zotero
                  文献库或外部大型数据集」、代码项目的「共享 SDK 仓库」，仅允许只读检索，严禁写入篡改。
                </p>
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  value={newAllowedPath}
                  onChange={(e) => setNewAllowedPath(e.target.value)}
                  placeholder="输入外部只读参考目录路径或通配规则（如 D:/Templates/** 或 ~/Zotero/storage/**）"
                  className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono"
                />
                <Button
                  size="sm"
                  onClick={() => void handleAddAllowedPath()}
                  disabled={!newAllowedPath.trim() || savingPaths}
                >
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  添加只读路径
                </Button>
              </div>

              {(activeProject.allowedPaths ?? []).length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                  暂未配置额外只读路径（当前仅允许访问项目主目录 {activeProject.path}）
                </div>
              ) : (
                <div className="space-y-1.5">
                  {(activeProject.allowedPaths ?? []).map((rule) => (
                    <div
                      key={rule}
                      className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-xs"
                    >
                      <span className="font-mono text-foreground">{rule}</span>
                      <button
                        type="button"
                        onClick={() => void handleRemoveAllowedPath(rule)}
                        disabled={savingPaths}
                        className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                        aria-label={`移除只读路径：${rule}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* 项目创建三步向导弹窗 */}
      <ProjectCreationWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onSuccess={(created) => {
          setProjects((prev) => [created, ...prev.filter((p) => p.id !== created.id)]);
          setSelectedProjectId(created.id);
          if (created.projectType) {
            setSelectedArchetype(created.projectType);
          }
        }}
      />
    </div>
  );
}
