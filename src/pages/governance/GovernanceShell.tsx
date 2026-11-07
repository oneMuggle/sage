import { ArrowLeft, CheckCircle2 } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { ProjectTypeBadge } from '../../features/project-type';
import { getArchetypeBlueprint } from '../../features/project-type/archetypeBlueprints';
import { RulesPanel } from '../../features/rules/RulesPanel';
import type { ProjectScaffoldResult, ProjectSummary } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

import {
  GOVERNANCE_TABS,
  governanceHref,
  parseGovernanceTab,
  type GovernanceTab,
} from './governanceTabs';
import { FilesSection } from './sections/FilesSection';
import { KnowledgeSection } from './sections/KnowledgeSection';
import { OverviewSection } from './sections/OverviewSection';
import { SettingsSection } from './sections/SettingsSection';
import { useGovernanceProject, type GovernanceData } from './useGovernanceProject';

// eslint-disable-next-line react-refresh/only-export-components
export { auditProjectGovernancePageGovernance } from './governanceAudit';

const EN_TAB_LABELS: Record<string, string> = {
  overview: 'Overview',
  rules: 'Rules',
  knowledge: 'Knowledge',
  files: 'Files',
  settings: 'Settings',
};

interface DeadlineBadgeProps {
  deadline: NonNullable<GovernanceData['upcomingDeadline']>;
}

function DeadlineBadge({ deadline }: DeadlineBadgeProps) {
  const { daysLeft, title, dueDate } = deadline;
  const tone =
    daysLeft < 0
      ? 'bg-destructive/15 text-destructive'
      : daysLeft <= 7
        ? 'bg-amber-500/15 text-amber-600'
        : 'bg-emerald-500/15 text-emerald-600';
  const label =
    daysLeft < 0
      ? `已逾期 ${Math.abs(daysLeft)} 天 · ${title}`
      : daysLeft <= 7
        ? `距截止仅剩 ${daysLeft} 天 · ${title}`
        : `下一节点：${title} (${dueDate})`;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-ui-2xs font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

interface GovernanceHeaderProps {
  project: ProjectSummary;
  deadline: GovernanceData['upcomingDeadline'];
  onBack: () => void;
}

function GovernanceHeader({ project, deadline, onBack }: GovernanceHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          onClick={onBack}
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
        {deadline && <DeadlineBadge deadline={deadline} />}
      </div>
    </div>
  );
}

interface ScaffoldFeedbackProps {
  result: ProjectScaffoldResult;
  blueprintLabel: string;
}

function ScaffoldFeedback({ result, blueprintLabel }: ScaffoldFeedbackProps) {
  return (
    <div
      className="flex items-center gap-2 mx-4 mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-foreground"
      data-testid="studio-scaffold-feedback"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
      <span>
        已按「{blueprintLabel}」完成初始化：新建目录 {result.createdDirectories.length} 个、新建文件{' '}
        {result.createdFiles.join(', ') || '无（保留已有 SAGE.md）'}、导入约束{' '}
        {result.importedConstraintsCount} 条、初始化里程碑 {result.seededMilestonesCount} 项。
      </span>
    </div>
  );
}

interface GovernanceTabBarProps {
  activeTab: GovernanceTab;
  locale: string;
  onChangeTab: (tab: string) => void;
}

function GovernanceTabBar({ activeTab, locale, onChangeTab }: GovernanceTabBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 pt-3" role="tablist">
      {GOVERNANCE_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          onClick={() => onChangeTab(tab.id)}
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
  );
}

interface GovernanceContentProps {
  activeTab: GovernanceTab;
  data: GovernanceData;
  projectId: string;
  onStartSession: () => void;
  onChangeTab: (tab: string) => void;
}

function GovernanceContent({
  activeTab,
  data,
  projectId,
  onStartSession,
  onChangeTab,
}: GovernanceContentProps) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
      <Card className="p-4 space-y-4">
        {activeTab === 'overview' && (
          <OverviewSection data={data} onStartSession={onStartSession} onChangeTab={onChangeTab} />
        )}
        {activeTab === 'rules' && (
          <RulesPanel
            projectId={projectId}
            onOpenSource={(entry) => {
              if (entry.layer === 'playbook') onChangeTab('overview');
            }}
          />
        )}
        {activeTab === 'knowledge' && (
          <KnowledgeSection data={data} onStartSession={onStartSession} />
        )}
        {activeTab === 'files' && <FilesSection projectId={projectId} />}
        {activeTab === 'settings' && (
          <SettingsSection data={data} activeTab={activeTab} onStartSession={onStartSession} />
        )}
      </Card>
    </div>
  );
}

function GovernanceEmptyState({ onBack }: { onBack: () => void }) {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground"
      data-testid="governance-loading"
    >
      <p>项目不存在或加载失败</p>
      <Button variant="secondary" size="sm" onClick={onBack}>
        返回工作台
      </Button>
    </div>
  );
}

function useGovernanceActions(projectId: string | undefined, data: GovernanceData) {
  const navigate = useNavigate();

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

  const goBack = () => navigate('/projects');

  return { changeTab, openChat, goBack };
}

export function GovernanceShell() {
  const { projectId } = useParams<{ projectId: string }>();
  const { locale } = useI18n();
  const [searchParams] = useSearchParams();
  const data = useGovernanceProject(projectId);
  const activeTab = parseGovernanceTab(searchParams.get('tab'));
  const { changeTab, openChat, goBack } = useGovernanceActions(projectId, data);

  if (!data.project) {
    return <GovernanceEmptyState onBack={goBack} />;
  }

  const project = data.project;

  return (
    <div
      className="flex-1 flex flex-col min-h-0 overflow-hidden"
      data-testid="project-governance-page"
    >
      <GovernanceHeader project={project} deadline={data.upcomingDeadline} onBack={goBack} />
      {data.scaffoldResult && (
        <ScaffoldFeedback
          result={data.scaffoldResult}
          blueprintLabel={getArchetypeBlueprint(data.activeProjectType).label}
        />
      )}
      <GovernanceTabBar activeTab={activeTab} locale={locale} onChangeTab={changeTab} />
      <GovernanceContent
        activeTab={activeTab}
        data={data}
        projectId={project.id}
        onStartSession={openChat}
        onChangeTab={changeTab}
      />
    </div>
  );
}

export default GovernanceShell;
