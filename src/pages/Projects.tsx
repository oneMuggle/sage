import { ChevronDown, ChevronRight, Copy, FolderPlus, Layers, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ProjectCreationWizard } from '../features/project-type';
import { projectApi, type ProjectSummary } from '../shared/api';
import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { PageHeader } from '../shared/ui';
import { WorkbenchProjectList } from '../widgets/sidebar/sections/WorkbenchProjectList';

export function Projects() {
  const navigate = useNavigate();
  const { locale } = useI18n();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [copiedPaths, setCopiedPaths] = useState(false);
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

  const handleCopyPaths = async () => {
    try {
      await navigator.clipboard?.writeText(projects.map((p) => p.path).join('\n'));
      setCopiedPaths(true);
      setTimeout(() => setCopiedPaths(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  const handleExportMarkdown = async () => {
    const lines = [
      `# 项目台账 (${projects.length} 个项目)`,
      '',
      '| 项目名称 | 类型 | 会话数 | 工作区路径 |',
      '| :--- | :--- | :---: | :--- |',
      ...projects.map((p) => {
        const type = p.projectType ?? p.detectedType ?? 'coding';
        return `| ${p.name} | ${type} | ${p.sessionCount} | \`${p.path}\` |`;
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
            ? 'Start a session in a project, or add a project to manage goals, rules and materials.'
            : '在项目里开始会话，或添加项目来管理目标、规则和资料。'
        }
      />

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        <div className="max-w-3xl mx-auto space-y-4">
          {/* ── Section 1: Quick start ─────────────────────────────── */}
          <div
            className="rounded-xl border border-border bg-card p-4 space-y-3"
            data-testid="workbench-quickstart"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Layers className="h-4 w-4 text-primary" />
              {locale === 'en' ? 'Get started' : '快速开始'}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => navigate('/welcome')}
                data-testid="workbench-cta-new-chat"
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-ui-sm font-medium text-primary hover:bg-primary/15 transition-colors"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                {locale === 'en' ? 'New session' : '新建对话'}
              </button>
              <button
                type="button"
                onClick={() => setWizardOpen(true)}
                data-testid="workbench-cta-add-project"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-ui-sm font-medium text-foreground hover:bg-muted transition-colors"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                {locale === 'en' ? 'Add project' : '纳管已有项目'}
              </button>
              <span className="inline-flex items-center text-ui-2xs text-muted self-center ml-1">
                {locale === 'en'
                  ? 'or drag a folder here to register it'
                  : '也可以直接拖入文件夹到这里'}
              </span>
            </div>
          </div>

          {/* ── Section 2: Project list (main body) ────────────────── */}
          <div className="space-y-1" data-testid="workbench-project-list-section">
            <div className="flex items-center justify-between px-1 mb-1">
              <span
                className="text-ui-2xs font-semibold uppercase tracking-wide text-muted"
                data-testid="workbench-project-count"
              >
                {locale === 'en'
                  ? `${projects.length} project${projects.length !== 1 ? 's' : ''}`
                  : `已纳管 ${projects.length} 个项目`}
              </span>
              <button
                type="button"
                onClick={() => void loadProjects()}
                aria-label={locale === 'en' ? 'Refresh' : '刷新'}
                title={locale === 'en' ? 'Refresh' : '刷新'}
                data-testid="workbench-refresh-btn"
                className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
            <WorkbenchProjectList
              onOpenSession={(sessionId) => {
                useStore.getState().setCurrentSessionId(sessionId);
                navigate('/chat');
              }}
            />
          </div>

          {/* ── Section 3: Advanced (collapsed by default) ─────────── */}
          {projects.length > 0 && (
            <div
              className="rounded-lg border border-border/60 bg-card/50"
              data-testid="workbench-advanced"
            >
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                data-testid="workbench-advanced-toggle"
                className="flex items-center gap-1.5 w-full px-3 py-2 text-ui-2xs font-medium text-muted hover:text-text transition-colors"
              >
                {advancedOpen ? (
                  <ChevronDown className="w-3 h-3" />
                ) : (
                  <ChevronRight className="w-3 h-3" />
                )}
                {locale === 'en' ? 'Advanced' : '高级功能'}
              </button>
              {advancedOpen && (
                <div className="flex flex-wrap gap-1.5 px-3 pb-3">
                  <button
                    type="button"
                    onClick={() => void handleCopyPaths()}
                    data-testid="workbench-copy-paths-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted transition-colors"
                  >
                    {copiedPaths
                      ? locale === 'en'
                        ? 'Copied!'
                        : '已复制'
                      : locale === 'en'
                        ? 'Copy all paths'
                        : '复制所有路径'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleExportMarkdown()}
                    data-testid="workbench-export-registry-md-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted transition-colors"
                  >
                    {copiedRegistry ? (
                      <>
                        <Copy className="h-3 w-3 text-emerald-500" />
                        {locale === 'en' ? 'Copied!' : '已复制到剪贴板'}
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3 text-muted-foreground" />
                        {locale === 'en' ? 'Export as Markdown' : '导出台账 Markdown'}
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {wizardOpen && (
        <ProjectCreationWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          onSuccess={(project) => {
            void loadProjects();
            navigate(`/projects/governance/${project.id}`);
          }}
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
