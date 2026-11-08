import { useSearchParams } from 'react-router-dom';

import { GitStatusWidget, WikiGenerationPanel } from '../../../features/project-type';
import {
  StudioMaterialsTabPanel,
  StudioProfileTabPanel,
} from '../../../features/project-type/StudioMaterialsAndProfilePanels';
import type { GovernanceData } from '../useGovernanceProject';

type KnowledgeTab = 'materials' | 'profile';
type GovernanceProject = NonNullable<GovernanceData['project']>;

const KNOWLEDGE_TABS: ReadonlyArray<{ id: KnowledgeTab; label: string }> = [
  { id: 'materials', label: '项目资料' },
  { id: 'profile', label: 'AI 记忆' },
];

function parseKnowledgeTab(raw: string | null): KnowledgeTab {
  return raw === 'profile' ? 'profile' : 'materials';
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
    <div className="space-y-3" data-testid="knowledge-section">
      <KnowledgeTabBar
        activeTab={activeTab}
        profileCount={data.profileEntries.length}
        onSelect={selectTab}
      />
      {activeTab === 'materials' && <MaterialsSubPanel data={data} project={project} />}
      {activeTab === 'profile' && <ProfileSubPanel data={data} project={project} />}
    </div>
  );
}
