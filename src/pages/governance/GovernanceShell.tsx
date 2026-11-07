import { ArrowLeft, CheckCircle2 } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { ProjectTypeBadge } from '../../features/project-type';
import { getArchetypeBlueprint } from '../../features/project-type/archetypeBlueprints';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

import { GOVERNANCE_TABS, governanceHref, parseGovernanceTab } from './governanceTabs';
import { FilesSection } from './sections/FilesSection';
import { KnowledgeSection } from './sections/KnowledgeSection';
import { OverviewSection } from './sections/OverviewSection';
import { SettingsSection } from './sections/SettingsSection';
import { useGovernanceProject } from './useGovernanceProject';

// eslint-disable-next-line react-refresh/only-export-components
export { auditProjectGovernancePageGovernance } from './governanceAudit';

const EN_TAB_LABELS: Record<string, string> = {
  overview: 'Overview',
  rules: 'Rules',
  knowledge: 'Knowledge',
  files: 'Files',
  settings: 'Settings',
};

export function GovernanceShell() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { locale } = useI18n();
  const [searchParams] = useSearchParams();
  const data = useGovernanceProject(projectId);
  const activeTab = parseGovernanceTab(searchParams.get('tab'));

  const changeTab = (tab: string) => {
    if (!projectId) return;
    navigate(governanceHref(projectId, parseGovernanceTab(tab)));
  };

  const openChat = async () => {
    const sessionId = await data.startSession();
    if (!sessionId) return;
    useStore.getState().setCurrentSessionId(sessionId);
    navigate('/chat');
  };

  if (!data.project) {
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

  const project = data.project;
  const blueprint = getArchetypeBlueprint(data.activeProjectType);

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden" data-testid="project-governance-page">
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
          {data.upcomingDeadline && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-ui-2xs font-medium ${
                data.upcomingDeadline.daysLeft < 0
                  ? 'bg-destructive/15 text-destructive'
                  : data.upcomingDeadline.daysLeft <= 7
                    ? 'bg-amber-500/15 text-amber-600'
                    : 'bg-emerald-500/15 text-emerald-600'
              }`}
            >
              {data.upcomingDeadline.daysLeft < 0
                ? `已逾期 ${Math.abs(data.upcomingDeadline.daysLeft)} 天 · ${data.upcomingDeadline.title}`
                : data.upcomingDeadline.daysLeft <= 7
                  ? `距截止仅剩 ${data.upcomingDeadline.daysLeft} 天 · ${data.upcomingDeadline.title}`
                  : `下一节点：${data.upcomingDeadline.title} (${data.upcomingDeadline.dueDate})`}
            </span>
          )}
        </div>
      </div>

      {data.scaffoldResult && (
        <div
          className="flex items-center gap-2 mx-4 mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-foreground"
          data-testid="studio-scaffold-feedback"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
          <span>
            已按「{blueprint.label}」完成初始化：新建目录{' '}
            {data.scaffoldResult.createdDirectories.length} 个、新建文件{' '}
            {data.scaffoldResult.createdFiles.join(', ') || '无（保留已有 SAGE.md）'}、导入约束{' '}
            {data.scaffoldResult.importedConstraintsCount} 条、初始化里程碑{' '}
            {data.scaffoldResult.seededMilestonesCount} 项。
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 pt-3" role="tablist">
        {GOVERNANCE_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => changeTab(tab.id)}
            data-testid={`governance-tab-${tab.id}`}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:text-foreground'
            }`}
          >
            {locale === 'en' ? EN_TAB_LABELS[tab.id] : tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
        <Card className="p-4 space-y-4">
          {activeTab === 'overview' && (
            <OverviewSection data={data} onStartSession={openChat} onChangeTab={changeTab} />
          )}
          {activeTab === 'rules' && <KnowledgeSection data={data} onStartSession={openChat} />}
          {activeTab === 'knowledge' && <KnowledgeSection data={data} onStartSession={openChat} />}
          {activeTab === 'files' && <FilesSection projectId={project.id} />}
          {activeTab === 'settings' && (
            <SettingsSection data={data} activeTab={activeTab} onStartSession={openChat} />
          )}
        </Card>
      </div>
    </div>
  );
}

export default GovernanceShell;
