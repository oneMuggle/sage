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
import { ProjectSection } from '../widgets/sidebar/sections/ProjectSection';

/** A spacious view of the same project APIs, not a second project registry. */
export function Projects() {
  const navigate = useNavigate();
  const { locale } = useI18n();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [copiedRegistry, setCopiedRegistry] = useState(false);

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
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
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

          <ProjectSection
            collapsed={false}
            onToggleCollapsed={() => undefined}
            presentation="workbench"
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
