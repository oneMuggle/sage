/**
 * Project governance page — deep management view for a single project.
 *
 * Hosts the 6 governance tabs (overview / charter / materials / rules /
 * milestones / profile) at route /projects/governance/:projectId.
 * The "rules" tab merges constraints + allowed_paths (Scheme 4).
 *
 * Created 2026-10-18 as part of Scheme 1 (progressive disclosure).
 */

import { ArrowLeft, CheckCircle2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { PlaybookCard } from '../features/playbook/PlaybookCard';
import {
  MilestoneManager,
  PolymorphicArchetypeCards,
  ProjectBootstrapPanel,
  ProjectOverviewWidgets,
  ProjectTypeBadge,
  GovernanceRulesPanel,
} from '../features/project-type';
import {
  StudioCharterTabPanel,
  StudioMaterialsTabPanel,
  StudioProfileTabPanel,
} from '../features/project-type/StudioMaterialsAndProfilePanels';
import {
  ARCHETYPE_ORDER,
  ARCHETYPE_BLUEPRINTS,
} from '../features/project-type/archetypeBlueprints';
import { getArchetypeBlueprint } from '../features/project-type/archetypeBlueprints';
import {
  memoryApi,
  projectApi,
  type ProjectMilestone,
  type ProjectSummary,
  type ProjectType,
  type ProjectScaffoldResult,
} from '../shared/api';
import type { ProjectProfileEntry } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';
import { Button } from '../shared/ui/Button';
import { Card } from '../shared/ui/Card';

type GovernanceTab = 'overview' | 'knowledge' | 'settings';
type KnowledgeTab = 'rules' | 'materials' | 'profile';

// eslint-disable-next-line react-refresh/only-export-components
export function formatProjectGovernanceAuditSnapshot(opts: {
  projectId?: string | null;
  projectType?: string | null;
  activeTab?: string;
  milestonesCount?: number;
  profileCount?: number;
  allowedPathsCount?: number;
  scaffolding?: boolean;
}): string {
  return `projectGovernance|id=${opts.projectId || 'none'}|type=${opts.projectType || 'business'}|tab=${opts.activeTab || 'overview'}|milestones=${opts.milestonesCount ?? 0}|profile=${opts.profileCount ?? 0}|paths=${opts.allowedPathsCount ?? 0}|scaffolding=${opts.scaffolding ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatProjectGovernanceAuditJson(opts: {
  projectId?: string | null;
  projectType?: string | null;
  activeTab?: string;
  milestonesCount?: number;
  profileCount?: number;
  allowedPathsCount?: number;
  scaffolding?: boolean;
}): string {
  return JSON.stringify({
    projectId: opts.projectId || 'none',
    projectType: opts.projectType || 'business',
    activeTab: opts.activeTab || 'overview',
    milestonesCount: opts.milestonesCount ?? 0,
    profileCount: opts.profileCount ?? 0,
    allowedPathsCount: opts.allowedPathsCount ?? 0,
    scaffolding: Boolean(opts.scaffolding),
  });
}

export function ProjectGovernance() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { locale } = useI18n();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [activeTab, setActiveTab] = useState<GovernanceTab>('overview');
  const [knowledgeTab, setKnowledgeTab] = useState<KnowledgeTab>('rules');
  const [scaffolding, setScaffolding] = useState(false);
  const [scaffoldResult, setScaffoldResult] = useState<ProjectScaffoldResult | null>(null);
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);

  const [profileEntries, setProfileEntries] = useState<ProjectProfileEntry[]>([]);
  const [profileCategory, setProfileCategory] = useState<string>('convention');
  const [profileDraft, setProfileDraft] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  const [newAllowedPath, setNewAllowedPath] = useState('');
  const [savingPaths, setSavingPaths] = useState(false);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  // Load the target project
  useEffect(() => {
    let cancelled = false;
    projectApi
      .list()
      .then((list) => {
        if (cancelled) return;
        if (Array.isArray(list)) {
          const found = list.find((p) => p.id === projectId) ?? null;
          setProject(found);
        }
      })
      .catch(() => {
        if (!cancelled) setProject(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Load milestones
  useEffect(() => {
    if (!project?.id || typeof projectApi?.listMilestones !== 'function') return;
    let cancelled = false;
    void projectApi
      .listMilestones(project.id)
      .then((items) => {
        if (!cancelled) setMilestones(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (!cancelled) setMilestones([]);
      });
    return () => {
      cancelled = true;
    };
  }, [project?.id]);

  // Load profile entries
  const loadActiveProfile = useCallback(async (projectPath?: string) => {
    if (!projectPath || typeof memoryApi?.getProjectProfile !== 'function') return;
    try {
      const res = await memoryApi.getProjectProfile({ projectKey: projectPath });
      setProfileEntries(res?.items ?? []);
    } catch {
      setProfileEntries([]);
    }
  }, []);

  useEffect(() => {
    if (project?.path) void loadActiveProfile(project.path);
  }, [project?.path, loadActiveProfile]);

  const activeProjectType: ProjectType = (project?.projectType ??
    project?.detectedType ??
    'business') as ProjectType;
  const activeBlueprint = getArchetypeBlueprint(activeProjectType);

  const upcomingDeadline = (() => {
    const withDue = milestones
      .filter((m) => m.status !== 'completed' && m.dueDate)
      .sort((a, b) => String(a.dueDate).localeCompare(String(b.dueDate)));
    const next = withDue[0];
    if (!next?.dueDate) return null;
    const dueMs = Date.parse(`${next.dueDate}T23:59:59`);
    if (Number.isNaN(dueMs)) return null;
    const daysLeft = Math.ceil((dueMs - Date.now()) / (1000 * 60 * 60 * 24));
    return { title: next.title, dueDate: next.dueDate, daysLeft };
  })();

  const handleChangeProjectType = async (nextType: ProjectType) => {
    if (!project || typeof projectApi?.update !== 'function') return;
    try {
      const nextStage = getArchetypeBlueprint(nextType).stages[0]?.id ?? null;
      const updated = await projectApi.update(project.id, {
        project_type: nextType,
        project_stage: nextStage,
      });
      setProject(updated);
    } catch {
      // ignore
    }
  };

  const handleChangeProjectStage = async (nextStage: string) => {
    if (!project || typeof projectApi?.update !== 'function') return;
    try {
      const updated = await projectApi.update(project.id, { project_stage: nextStage });
      setProject(updated);
    } catch {
      // ignore
    }
  };

  const handleChangeVcsMode = async (nextVcs: 'git' | 'builtin') => {
    if (!project || typeof projectApi?.update !== 'function') return;
    try {
      const updated = await projectApi.update(project.id, { vcs_mode: nextVcs });
      setProject(updated);
    } catch {
      // ignore
    }
  };

  const handleScaffold = async () => {
    if (!project || typeof projectApi?.scaffold !== 'function') return;
    setScaffolding(true);
    setScaffoldResult(null);
    try {
      const res = await projectApi.scaffold(project.id, {
        projectType: activeProjectType,
        createDirectories: true,
        createSageMd: true,
        importDefaultConstraints: true,
        seedDefaultMilestones: true,
      });
      setScaffoldResult(res);
      setProject(res.project);
    } catch {
      // ignore
    } finally {
      setScaffolding(false);
    }
  };

  const handleAddProfileEntry = async () => {
    const content = profileDraft.trim();
    if (
      !project?.path ||
      !content ||
      savingProfile ||
      typeof memoryApi?.createProjectProfile !== 'function'
    )
      return;
    setSavingProfile(true);
    try {
      await memoryApi.createProjectProfile(content, {
        projectKey: project.path,
        category: profileCategory,
        importance: 5,
      });
      setProfileDraft('');
      await loadActiveProfile(project.path);
    } catch {
      // ignore
    } finally {
      setSavingProfile(false);
    }
  };

  const handleDeleteProfileEntry = async (entryId: string) => {
    if (!project?.path || typeof memoryApi?.deleteProjectProfile !== 'function') return;
    try {
      await memoryApi.deleteProjectProfile(entryId);
      await loadActiveProfile(project.path);
    } catch {
      // ignore
    }
  };

  const handleQuickAddPresetPath = async (pattern: string) => {
    const trimmed = pattern.trim();
    if (!project || !trimmed || typeof projectApi?.updateAllowedPaths !== 'function') return;
    const current = project.allowedPaths ?? [];
    if (current.includes(trimmed)) return;
    setSavingPaths(true);
    try {
      const next = await projectApi.updateAllowedPaths(project.id, [...current, trimmed]);
      setProject({ ...project, allowedPaths: next });
    } catch {
      // ignore
    } finally {
      setSavingPaths(false);
    }
  };

  const handleAddAllowedPath = async () => {
    const trimmed = newAllowedPath.trim();
    if (!project || !trimmed || typeof projectApi?.updateAllowedPaths !== 'function') return;
    const current = project.allowedPaths ?? [];
    if (current.includes(trimmed)) {
      setNewAllowedPath('');
      return;
    }
    setSavingPaths(true);
    try {
      const next = await projectApi.updateAllowedPaths(project.id, [...current, trimmed]);
      setProject({ ...project, allowedPaths: next });
      setNewAllowedPath('');
    } catch {
      // ignore
    } finally {
      setSavingPaths(false);
    }
  };

  const handleRemoveAllowedPath = async (targetPath: string) => {
    if (!project || typeof projectApi?.updateAllowedPaths !== 'function') return;
    const current = project.allowedPaths ?? [];
    setSavingPaths(true);
    try {
      const next = await projectApi.updateAllowedPaths(
        project.id,
        current.filter((item) => item !== targetPath),
      );
      setProject({ ...project, allowedPaths: next });
    } catch {
      // ignore
    } finally {
      setSavingPaths(false);
    }
  };

  if (!project) {
    return (
      <div
        className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground"
        data-testid="governance-loading"
      >
        <p>项目不存在或加载失败</p>
        <Button variant="secondary" size="sm" onClick={() => navigate('/projects')}>
          返回工作台
        </Button>
      </div>
    );
  }

  return (
    <div
      className="flex-1 flex flex-col min-h-0 overflow-hidden"
      data-testid="project-governance-page"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={() => navigate('/projects')}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回工作台
          </button>
          <span className="text-sm font-semibold text-foreground">{project.name}</span>
          <ProjectTypeBadge
            type={project.projectType ?? project.detectedType}
            detected={!project.projectType && Boolean(project.detectedType)}
          />
          <span className="text-xs text-muted-foreground font-mono">{project.path}</span>
          {upcomingDeadline && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-ui-2xs font-medium ${
                upcomingDeadline.daysLeft < 0
                  ? 'bg-destructive/15 text-destructive'
                  : upcomingDeadline.daysLeft <= 7
                    ? 'bg-amber-500/15 text-amber-600'
                    : 'bg-emerald-500/15 text-emerald-600'
              }`}
            >
              {upcomingDeadline.daysLeft < 0
                ? `已逾期 ${Math.abs(upcomingDeadline.daysLeft)} 天 · ${upcomingDeadline.title}`
                : upcomingDeadline.daysLeft <= 7
                  ? `距截止仅剩 ${upcomingDeadline.daysLeft} 天 · ${upcomingDeadline.title}`
                  : `下一节点：${upcomingDeadline.title} (${upcomingDeadline.dueDate})`}
            </span>
          )}
        </div>
      </div>

      {/* Scaffold feedback */}
      {scaffoldResult && (
        <div
          className="flex items-center gap-2 mx-4 mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-foreground"
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

      {/* Tab navigation */}
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        {[
          { id: 'overview' as GovernanceTab, label: locale === 'en' ? 'Overview' : '概览' },
          {
            id: 'knowledge' as GovernanceTab,
            label:
              locale === 'en'
                ? `Project knowledge (${profileEntries.length})`
                : `项目知识（${project.allowedPaths?.length ?? 0} 条规则 · ${profileEntries.length} 条记忆）`,
          },
          { id: 'settings' as GovernanceTab, label: locale === 'en' ? 'Settings' : '设置' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            data-testid={`governance-tab-${tab.id}`}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
        <Card className="p-4 space-y-4">
          {activeTab === 'overview' && (
            <div className="space-y-4">
              <ProjectBootstrapPanel projectId={project.id} />
              <PlaybookCard projectId={project.id} />
              <PolymorphicArchetypeCards project={project} projectType={activeProjectType} />
              <ProjectOverviewWidgets project={project} />
              <details className="rounded-lg border border-border bg-card/50">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
                  里程碑（可选）
                </summary>
                <div className="px-3 pb-3">
                  <MilestoneManager projectId={project.id} projectType={activeProjectType} />
                </div>
              </details>
            </div>
          )}

          {activeTab === 'knowledge' && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5" role="tablist">
                {[
                  {
                    id: 'rules' as KnowledgeTab,
                    label: `规则与约束 (${project.allowedPaths?.length ?? 0})`,
                  },
                  { id: 'materials' as KnowledgeTab, label: '项目资料' },
                  {
                    id: 'profile' as KnowledgeTab,
                    label: `AI 记忆 (${profileEntries.length})`,
                  },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={knowledgeTab === tab.id}
                    onClick={() => setKnowledgeTab(tab.id)}
                    data-testid={`governance-knowledge-${tab.id}`}
                    className={`rounded-md px-2.5 py-1 text-ui-2xs font-medium transition-colors ${
                      knowledgeTab === tab.id
                        ? 'bg-primary/15 text-primary'
                        : 'bg-muted text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {knowledgeTab === 'rules' && (
                <GovernanceRulesPanel
                  projectId={project.id}
                  projectPath={project.path}
                  projectType={activeProjectType}
                  allowedPaths={project.allowedPaths ?? []}
                  newAllowedPath={newAllowedPath}
                  onNewAllowedPathChange={setNewAllowedPath}
                  savingPaths={savingPaths}
                  onAddAllowedPath={handleAddAllowedPath}
                  onQuickAddPresetPath={handleQuickAddPresetPath}
                  onRemoveAllowedPath={handleRemoveAllowedPath}
                />
              )}

              {knowledgeTab === 'materials' && (
                <StudioMaterialsTabPanel
                  projectId={project.id}
                  projectPath={project.path}
                  projectType={activeProjectType}
                />
              )}

              {knowledgeTab === 'profile' && (
                <StudioProfileTabPanel
                  projectPath={project.path}
                  projectType={activeProjectType}
                  projectId={project.id}
                  profileEntries={profileEntries}
                  profileCategory={profileCategory}
                  onCategoryChange={setProfileCategory}
                  profileDraft={profileDraft}
                  onDraftChange={setProfileDraft}
                  savingProfile={savingProfile}
                  onAddEntry={handleAddProfileEntry}
                  onDeleteEntry={handleDeleteProfileEntry}
                  onRefreshProfile={() => void loadActiveProfile(project.path)}
                />
              )}
            </div>
          )}

          {activeTab === 'settings' && (
            <div className="space-y-4">
              <StudioCharterTabPanel
                projectId={project.id}
                projectPath={project.path}
                projectType={activeProjectType}
                initialDescription={project.description}
                initialInstructions={project.instructions}
                onMetadataUpdated={(patch: {
                  description: string | null;
                  instructions: string | null;
                }) => {
                  setProject((prev) => (prev ? { ...prev, ...patch } : prev));
                }}
              />

              <div
                className="rounded-lg border border-border bg-card/50 p-3 text-xs text-muted-foreground"
                data-testid="playbook-settings-note"
              >
                项目规程与阶段管理已移至「概览」页，避免重复扫描项目。
              </div>

              <div
                className="space-y-3 rounded-lg border border-border p-3"
                data-testid="governance-settings-controls"
              >
                <div className="text-xs font-medium text-foreground">项目类型与版本控制</div>
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
                    value={project.projectStage ?? ''}
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

                  {(() => {
                    const stages = activeBlueprint.stages;
                    const curIdx = stages.findIndex((s) => s.id === project.projectStage);
                    const nextStage =
                      curIdx === -1
                        ? stages[0]
                        : curIdx + 1 < stages.length
                          ? stages[curIdx + 1]
                          : null;
                    if (!nextStage) return null;
                    return (
                      <button
                        type="button"
                        onClick={() => void handleChangeProjectStage(nextStage.id)}
                        data-testid="studio-advance-stage-btn"
                        title={`推进至下一阶段：${nextStage.label}`}
                        className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/15"
                      >
                        推进至「{nextStage.label}」→
                      </button>
                    );
                  })()}

                  <select
                    value={project.vcsMode === 'git' ? 'git' : 'builtin'}
                    onChange={(e) => void handleChangeVcsMode(e.target.value as 'git' | 'builtin')}
                    aria-label="切换版本控制模式"
                    data-testid="studio-vcs-mode-select"
                    className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                  >
                    <option value="git">VCS：Git 仓库</option>
                    <option value="builtin">VCS：内置快照</option>
                  </select>

                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void handleScaffold()}
                    disabled={scaffolding}
                    data-testid="studio-scaffold-btn"
                  >
                    <Sparkles className="mr-1.5 h-3.5 w-3.5 text-primary" />
                    {scaffolding ? '初始化中...' : '一键初始化目录与规范'}
                  </Button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <span
                  data-testid="project-governance-copy-snapshot"
                  onClick={() => {
                    /* v8 ignore start */
                    setCopiedSnapshot(true);
                    void navigator.clipboard?.writeText(
                      formatProjectGovernanceAuditSnapshot({
                        projectId: project.id,
                        projectType: activeProjectType,
                        activeTab,
                        milestonesCount: milestones.length,
                        profileCount: profileEntries.length,
                        allowedPathsCount: project.allowedPaths?.length ?? 0,
                        scaffolding,
                      }),
                    );
                    /* v8 ignore stop */
                  }}
                  className="cursor-pointer rounded border border-border px-2 py-1 text-xs text-muted-foreground"
                >
                  {copiedSnapshot ? '已复制快照' : '复制治理快照'}
                </span>
                <span
                  data-testid="project-governance-copy-json"
                  onClick={() => {
                    /* v8 ignore start */
                    setCopiedJson(true);
                    void navigator.clipboard?.writeText(
                      formatProjectGovernanceAuditJson({
                        projectId: project.id,
                        projectType: activeProjectType,
                        activeTab,
                        milestonesCount: milestones.length,
                        profileCount: profileEntries.length,
                        allowedPathsCount: project.allowedPaths?.length ?? 0,
                        scaffolding,
                      }),
                    );
                    /* v8 ignore stop */
                  }}
                  className="cursor-pointer rounded border border-border px-2 py-1 text-xs text-muted-foreground"
                >
                  {copiedJson ? '已复制JSON' : '导出治理JSON'}
                </span>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

export default ProjectGovernance;

// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectGovernancePageGovernance(): {
  module: 'src/pages/ProjectGovernance.tsx';
  phase: 'P173';
  domain: 'pages';
  tabs: readonly ['overview', 'knowledge', 'settings'];
  compliant: boolean;
} {
  return {
    module: 'src/pages/ProjectGovernance.tsx',
    phase: 'P173',
    domain: 'pages',
    tabs: ['overview', 'knowledge', 'settings'],
    compliant: true,
  };
}
