import { useSearchParams } from 'react-router-dom';

import {
  GitStatusWidget,
  GovernanceRulesPanel,
  WikiGenerationPanel,
} from '../../../features/project-type';
import {
  StudioMaterialsTabPanel,
  StudioProfileTabPanel,
} from '../../../features/project-type/StudioMaterialsAndProfilePanels';
import type { GovernanceData } from '../useGovernanceProject';

type KnowledgeTab = 'rules' | 'materials' | 'profile';
type GovernanceProject = NonNullable<GovernanceData['project']>;

const KNOWLEDGE_TABS: ReadonlyArray<{ id: KnowledgeTab; label: string }> = [
  { id: 'rules', label: '规则与约束' },
  { id: 'materials', label: '项目资料' },
  { id: 'profile', label: 'AI 记忆' },
];

function parseKnowledgeTab(raw: string | null): KnowledgeTab {
  if (raw === 'wiki' || raw === 'materials') return 'materials';
  if (raw === 'profile') return 'profile';
  return 'rules';
}

interface KnowledgeTabBarProps {
  activeTab: KnowledgeTab;
  profileCount: number;
  onSelect: (tab: KnowledgeTab) => void;
}

function KnowledgeTabBar({ activeTab, profileCount, onSelect }: KnowledgeTabBarProps) {
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist">
      {KNOWLEDGE_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          onClick={() => onSelect(tab.id)}
          data-testid={`governance-knowledge-${tab.id}`}
          className={`rounded-md px-2.5 py-1 text-ui-2xs font-medium transition-colors ${
            activeTab === tab.id
              ? 'bg-primary/15 text-primary'
              : 'bg-muted text-muted-foreground hover:text-foreground'
          }`}
        >
          {tab.label}
          {tab.id === 'profile' ? ` (${profileCount})` : ''}
        </button>
      ))}
    </div>
  );
}

interface SubPanelProps {
  data: GovernanceData;
  project: GovernanceProject;
}

function RulesSubPanel({ data, project }: SubPanelProps) {
  return (
    <GovernanceRulesPanel
      projectId={project.id}
      projectPath={project.path}
      projectType={data.activeProjectType}
      allowedPaths={project.allowedPaths ?? []}
      newAllowedPath={data.newAllowedPath}
      onNewAllowedPathChange={data.setNewAllowedPath}
      savingPaths={data.savingPaths}
      onAddAllowedPath={data.addAllowedPath}
      onQuickAddPresetPath={data.quickAddPresetPath}
      onRemoveAllowedPath={data.removeAllowedPath}
    />
  );
}

function MaterialsSubPanel({ data, project }: SubPanelProps) {
  const showGit = data.activeProjectType === 'coding' || project.vcsMode === 'git';
  return (
    <div className="space-y-3">
      <StudioMaterialsTabPanel
        projectId={project.id}
        projectPath={project.path}
        projectType={data.activeProjectType}
      />
      {showGit && <GitStatusWidget projectId={project.id} />}
      <WikiGenerationPanel projectId={project.id} projectType={data.activeProjectType} />
    </div>
  );
}

function ProfileSubPanel({ data, project }: SubPanelProps) {
  return (
    <StudioProfileTabPanel
      projectPath={project.path}
      projectType={data.activeProjectType}
      projectId={project.id}
      profileEntries={data.profileEntries}
      profileCategory={data.profileCategory}
      onCategoryChange={data.setProfileCategory}
      profileDraft={data.profileDraft}
      onDraftChange={data.setProfileDraft}
      savingProfile={data.savingProfile}
      onAddEntry={data.addProfileEntry}
      onDeleteEntry={data.deleteProfileEntry}
      onRefreshProfile={() => void data.reload()}
    />
  );
}

export interface KnowledgeSectionProps {
  data: GovernanceData;
  onStartSession: () => void;
}

export function KnowledgeSection({ data }: KnowledgeSectionProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = parseKnowledgeTab(searchParams.get('knowledge'));
  if (!data.project) return null;
  const project = data.project;

  const selectTab = (tab: KnowledgeTab) => {
    const next = new URLSearchParams(searchParams);
    next.set('knowledge', tab);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-3">
      <KnowledgeTabBar
        activeTab={activeTab}
        profileCount={data.profileEntries.length}
        onSelect={selectTab}
      />
      {activeTab === 'rules' && <RulesSubPanel data={data} project={project} />}
      {activeTab === 'materials' && <MaterialsSubPanel data={data} project={project} />}
      {activeTab === 'profile' && <ProfileSubPanel data={data} project={project} />}
    </div>
  );
}
