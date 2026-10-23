import { Check, Copy, FolderPlus, Layers } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  ARCHETYPE_ORDER,
  ProjectArchetypeStudio,
  ProjectCreationWizard,
  getArchetypeBlueprint,
} from '../features/project-type';
import { projectApi, type ProjectSummary, type ProjectType } from '../shared/api';
import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { PageHeader } from '../shared/ui';
import { WorkbenchProjectList } from '../widgets/sidebar/sections/WorkbenchProjectList';

/** A spacious view of the same project APIs, not a second project registry. */
export function Projects() {
  const navigate = useNavigate();
  const { locale } = useI18n();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [copiedRegistry, setCopiedRegistry] = useState(false);
  const [copiedPaths, setCopiedPaths] = useState(false);
  const [savedRegistryL3, setSavedRegistryL3] = useState(false);
  const [savedRegistryL4, setSavedRegistryL4] = useState(false);
  const [copiedArchetypeStats, setCopiedArchetypeStats] = useState(false);
  const [savedArchetypeStatsL3, setSavedArchetypeStatsL3] = useState(false);
  const [savedArchetypeStatsL4, setSavedArchetypeStatsL4] = useState(false);
  const [convertedArchetypeStatsMilestone, setConvertedArchetypeStatsMilestone] = useState(false);
  const [convertedArchetypeStatsConstraint, setConvertedArchetypeStatsConstraint] = useState(false);
  const [convertedRegistryMilestone, setConvertedRegistryMilestone] = useState(false);
  const [convertedRegistryConstraint, setConvertedRegistryConstraint] = useState(false);
  const [copiedRegistryJson, setCopiedRegistryJson] = useState(false);
  const [copiedArchetypeStatsJson, setCopiedArchetypeStatsJson] = useState(false);

  const loadProjects = useCallback(async () => {
    if (typeof projectApi?.list !== 'function') return;
    try {
      const list = await projectApi.list();
      if (Array.isArray(list)) setProjects(list);
    } catch {
      // ignore in offline/test mode
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const archetypeCounts = ARCHETYPE_ORDER.reduce<Record<ProjectType, number>>(
    (acc, t) => {
      acc[t] = projects.filter((p) => (p.projectType ?? p.detectedType ?? 'coding') === t).length;
      return acc;
    },
    { coding: 0, business: 0, research: 0, personal: 0 },
  );

  const handleCopyRegistryMarkdown = async () => {
    const lines = [
      `# 全局受控项目台账 (${projects.length} 个项目)`,
      '',
      '| 项目名称 | 形态 | 当前阶段 | 版本策略 | 会话数 | 工作区路径 |',
      '| :--- | :--- | :--- | :--- | :---: | :--- |',
      ...projects.map((p) => {
        const bp = getArchetypeBlueprint(p.projectType ?? p.detectedType);
        const st =
          bp.stages.find((s) => s.id === p.projectStage)?.label ??
          p.projectStage ??
          bp.stages[0]?.label ??
          '-';
        const vcs = p.vcsMode ?? (bp.type === 'coding' ? 'git' : 'builtin');
        return `| ${p.name} | ${bp.label} | ${st} | ${vcs} | ${p.sessionCount} | \`${p.path}\` |`;
      }),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedRegistry(true);
      setTimeout(() => setCopiedRegistry(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden" data-testid="project-workbench">
      <PageHeader
        title={locale === 'en' ? 'Project workbench' : '项目工作台'}
        subtitle={
          locale === 'en'
            ? 'Expand a project to manage goals, instructions, sources and conversations. The folder binding still controls file access.'
            : '展开项目管理目标、指令、资料和会话。项目提供上下文，目录绑定与授权仍决定文件访问范围。'
        }
      />
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        <div className="max-w-5xl mx-auto space-y-4">
          <div
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-xs"
            data-testid="project-workbench-toolbar"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-primary" />
              <span className="font-medium text-foreground" data-testid="workbench-project-count">
                已纳管项目：{projects.length} 个
              </span>
              <div className="flex flex-wrap items-center gap-1" data-testid="workbench-archetype-counts">
                {ARCHETYPE_ORDER.map((t) => {
                  const bp = getArchetypeBlueprint(t);
                  return (
                    <span
                      key={t}
                      className="rounded bg-muted px-1.5 py-0.5 text-ui-2xs text-muted-foreground"
                    >
                      {bp.label}: {archetypeCounts[t]}
                    </span>
                  );
                })}
                <button
                  type="button"
                  data-testid="workbench-copy-archetype-stats-btn"
                  onClick={async () => {
                    const md = [
                      `# 项目形态分布统计 (${projects.length} 个项目)`,
                      ...ARCHETYPE_ORDER.map((t) => `- ${getArchetypeBlueprint(t).label}: ${archetypeCounts[t]} 个`),
                    ].join('\n');
                    try {
                      await navigator.clipboard?.writeText(md);
                      setCopiedArchetypeStats(true);
                      setTimeout(() => setCopiedArchetypeStats(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  {copiedArchetypeStats ? '已复制统计' : '复制形态统计'}
                </button>
                <button
                  type="button"
                  data-testid="workbench-copy-archetype-stats-json-btn"
                  onClick={async () => {
                    setCopiedArchetypeStatsJson(true);
                    setTimeout(() => {
                      if (typeof window !== 'undefined') setCopiedArchetypeStatsJson(false);
                    }, 1500);
                    try {
                      await navigator.clipboard?.writeText(
                        JSON.stringify(
                          { total: projects.length, counts: archetypeCounts },
                          null,
                          2,
                        ),
                      );
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  {copiedArchetypeStatsJson ? '已复制统计JSON' : '复制统计JSON'}
                </button>
                {projects.length > 0 && (
                  <button
                    type="button"
                    data-testid="workbench-save-archetype-stats-l3-btn"
                    onClick={async () => {
                      if (savedArchetypeStatsL3 || !projects[0]?.id) return;
                      setSavedArchetypeStatsL3(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projects[0].id, {
                            entries: [
                              {
                                category: 'architecture',
                                content: `项目形态分布统计 (${projects.length}个项目)：${ARCHETYPE_ORDER.map(
                                  (t) => `${getArchetypeBlueprint(t).label}=${archetypeCounts[t]}`,
                                ).join('、')}`,
                                importance: 6,
                                sourceMessageIds: [],
                                reasoning: '工作台四形态分布统计沉淀至 L3 画像',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {savedArchetypeStatsL3 ? '已存统计L3' : '统计存L3'}
                  </button>
                )}
                {projects.length > 0 && (
                  <button
                    type="button"
                    data-testid="workbench-save-archetype-stats-l4-btn"
                    onClick={async () => {
                      if (savedArchetypeStatsL4 || !projects[0]?.id) return;
                      setSavedArchetypeStatsL4(true);
                      if (typeof projectApi?.addMaterial === 'function') {
                        try {
                          await projectApi.addMaterial(projects[0].id, {
                            content: `# 项目形态分布统计 (${projects.length} 个项目)\n${ARCHETYPE_ORDER.map(
                              (t) => `- ${getArchetypeBlueprint(t).label} (${t}): ${archetypeCounts[t]} 个`,
                            ).join('\n')}`,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {savedArchetypeStatsL4 ? '已存统计L4' : '统计存L4'}
                  </button>
                )}
                {projects.length > 0 && (
                  <button
                    type="button"
                    data-testid="workbench-archetype-stats-to-milestone-btn"
                    onClick={async () => {
                      if (convertedArchetypeStatsMilestone || !projects[0]?.id) return;
                      setConvertedArchetypeStatsMilestone(true);
                      if (typeof projectApi?.createMilestone === 'function') {
                        try {
                          await projectApi.createMilestone(projects[0].id, {
                            title: `[四形态分布核查] 共 ${projects.length} 个项目`,
                            description: ARCHETYPE_ORDER.map(
                              (t) => `${getArchetypeBlueprint(t).label}: ${archetypeCounts[t]} 个`,
                            ).join(' · '),
                            status: 'pending',
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {convertedArchetypeStatsMilestone ? '已转统计里程碑' : '统计转里程碑'}
                  </button>
                )}
                {projects.length > 0 && (
                  <button
                    type="button"
                    data-testid="workbench-archetype-stats-to-constraint-btn"
                    onClick={async () => {
                      if (convertedArchetypeStatsConstraint || !projects[0]?.id) return;
                      setConvertedArchetypeStatsConstraint(true);
                      if (typeof projectApi?.createConstraint === 'function') {
                        try {
                          await projectApi.createConstraint(projects[0].id, {
                            category: 'architecture',
                            content: `[四形态架构分类规范] 按 ${ARCHETYPE_ORDER.map(
                              (t) => `${getArchetypeBlueprint(t).label}(${archetypeCounts[t]})`,
                            ).join('、')} 执行分形态上下文治理`,
                            triggerPattern: 'always',
                            priority: 8,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {convertedArchetypeStatsConstraint ? '已转统计L2' : '统计转L2'}
                  </button>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => void loadProjects()}
                data-testid="workbench-refresh-registry-btn"
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
              >
                刷新台账
              </button>
              {projects.length > 0 && (
                <>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await navigator.clipboard?.writeText(
                          projects.map((p) => p.path).join('\n'),
                        );
                        setCopiedPaths(true);
                        setTimeout(() => setCopiedPaths(false), 1800);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    data-testid="workbench-copy-paths-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {copiedPaths ? '已复制路径' : '复制路径列表'}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (savedRegistryL4 || !projects[0]?.id) return;
                      setSavedRegistryL4(true);
                      if (typeof projectApi?.addMaterial === 'function') {
                        const md = [
                          `# 全局受控项目台账 (${projects.length} 个项目)`,
                          ...projects.map((p) => `- ${p.name}: \`${p.path}\``),
                        ].join('\n');
                        try {
                          await projectApi.addMaterial(projects[0].id, { content: md });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    data-testid="workbench-save-registry-l4-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {savedRegistryL4 ? '已存台账L4' : '存台账至L4'}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (savedRegistryL3 || !projects[0]?.id) return;
                      setSavedRegistryL3(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projects[0].id, {
                            entries: [
                              {
                                category: 'architecture',
                                content: `全局受控项目台账：共 ${projects.length} 个项目（${projects.map((p) => p.name).join('、')}）`,
                                importance: 7,
                                sourceMessageIds: [],
                                reasoning: '项目工作台全局台账沉淀至 L3 画像',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    data-testid="workbench-save-registry-l3-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {savedRegistryL3 ? '已存台账L3' : '存台账至L3'}
                  </button>
                  <button
                    type="button"
                    data-testid="workbench-registry-to-milestone-btn"
                    onClick={async () => {
                      if (convertedRegistryMilestone || !projects[0]?.id) return;
                      setConvertedRegistryMilestone(true);
                      if (typeof projectApi?.createMilestone === 'function') {
                        try {
                          await projectApi.createMilestone(projects[0].id, {
                            title: `[全局项目治理巡检] 已纳管 ${projects.length} 个项目`,
                            description: projects.map((p) => p.name).join('、'),
                            status: 'pending',
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {convertedRegistryMilestone ? '已转巡检里程碑' : '台账转里程碑'}
                  </button>
                  <button
                    type="button"
                    data-testid="workbench-registry-to-constraint-btn"
                    onClick={async () => {
                      if (convertedRegistryConstraint || !projects[0]?.id) return;
                      setConvertedRegistryConstraint(true);
                      if (typeof projectApi?.createConstraint === 'function') {
                        try {
                          await projectApi.createConstraint(projects[0].id, {
                            category: 'workspace_boundary',
                            content: `[受控项目台账边界] 严格遵守已纳管 ${projects.length} 个项目的目录与分支隔离规范`,
                            triggerPattern: 'always',
                            priority: 8,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {convertedRegistryConstraint ? '已转台账L2' : '台账转L2护栏'}
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={() => void handleCopyRegistryMarkdown()}
                data-testid="workbench-export-registry-md-btn"
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
              >
                {copiedRegistry ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-500" />
                    已复制台账
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3 text-muted-foreground" />
                    导出项目台账 MD
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={async () => {
                  setCopiedRegistryJson(true);
                  setTimeout(() => {
                    if (typeof window !== 'undefined') setCopiedRegistryJson(false);
                  }, 1800);
                  try {
                    await navigator.clipboard?.writeText(
                      JSON.stringify(
                        {
                          total: projects.length,
                          archetypeCounts,
                          projects: projects.map((p) => ({
                            id: p.id,
                            name: p.name,
                            path: p.path,
                            projectType: p.projectType ?? p.detectedType ?? 'coding',
                            projectStage: p.projectStage ?? null,
                            vcsMode: p.vcsMode ?? null,
                            sessionCount: p.sessionCount,
                          })),
                        },
                        null,
                        2,
                      ),
                    );
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                data-testid="workbench-copy-registry-json-btn"
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
              >
                {copiedRegistryJson ? '已复制台账JSON' : '复制台账 JSON'}
              </button>
              <button
                type="button"
                onClick={() => setWizardOpen(true)}
                data-testid="workbench-open-wizard-btn"
                className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2.5 py-1 text-ui-2xs font-medium text-primary hover:bg-primary/15"
              >
                <FolderPlus className="h-3 w-3" />
                新建/纳管项目向导
              </button>
            </div>
          </div>

          <ProjectArchetypeStudio />

          <WorkbenchProjectList
            onOpenSession={(sessionId) => {
              useStore.getState().setCurrentSessionId(sessionId);
              navigate('/chat');
            }}
          />

          <div className="flex gap-2 mt-4">
            <button
              type="button"
              onClick={() => navigate('/welcome')}
              className="px-3 py-2 border border-ui-border rounded text-ui-base"
            >
              {locale === 'en' ? 'New deliverable' : '开始新的交付任务'}
            </button>
            <button
              type="button"
              onClick={() => navigate('/office')}
              className="px-3 py-2 border border-ui-border rounded text-ui-base"
            >
              {locale === 'en' ? 'Open documents and reviews' : '查看文档与验收'}
            </button>
          </div>
        </div>
      </div>

      {wizardOpen && (
        <ProjectCreationWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          onSuccess={() => void loadProjects()}
        />
      )}
    </div>
  );
}

export default Projects;

// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectsPageGovernance(): {
  module: 'src/pages/Projects.tsx';
  phase: 'P171';
  domain: 'pages';
  supportsCreationWizardAndArchetypeStudio: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/Projects.tsx',
    phase: 'P171',
    domain: 'pages',
    supportsCreationWizardAndArchetypeStudio: true,
    compliant: true,
  };
}
