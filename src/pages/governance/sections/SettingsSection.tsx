import { Sparkles } from 'lucide-react';
import { useState } from 'react';

import { ProjectBootstrapPanel, ProjectOverviewWidgets } from '../../../features/project-type';
import { StudioCharterTabPanel } from '../../../features/project-type/StudioMaterialsAndProfilePanels';
import {
  ARCHETYPE_BLUEPRINTS,
  ARCHETYPE_ORDER,
  getArchetypeBlueprint,
  type ArchetypeStageMeta,
} from '../../../features/project-type/archetypeBlueprints';
import type { ProjectType } from '../../../shared/api';
import { Button } from '../../../shared/ui/Button';
import {
  formatProjectGovernanceAuditJson,
  formatProjectGovernanceAuditSnapshot,
} from '../governanceAudit';
import type { GovernanceData } from '../useGovernanceProject';

type GovernanceProject = NonNullable<GovernanceData['project']>;

const SELECT_CLASS =
  'rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground';

export interface SettingsSectionProps {
  data: GovernanceData;
  activeTab: string;
  onStartSession: () => void;
}

interface BootstrapBlockProps {
  project: GovernanceProject;
  projectType: ProjectType;
  onReload: () => Promise<void>;
}

function BootstrapBlock({ project, projectType, onReload }: BootstrapBlockProps) {
  return (
    <>
      <ProjectBootstrapPanel projectId={project.id} />
      <StudioCharterTabPanel
        projectId={project.id}
        projectPath={project.path}
        projectType={projectType}
        initialDescription={project.description}
        initialInstructions={project.instructions}
        onMetadataUpdated={(patch: { description: string | null; instructions: string | null }) => {
          void onReload().then(() => patch);
        }}
      />
    </>
  );
}

function PlaybookNote() {
  return (
    <div
      className="rounded-lg border border-border bg-card/50 p-3 text-xs text-muted-foreground"
      data-testid="playbook-settings-note"
    >
      项目规程与阶段管理已移至「概览」页，避免重复扫描项目。
    </div>
  );
}

interface TypeSelectProps {
  value: ProjectType;
  onChange: (next: ProjectType) => void;
}

function TypeSelect({ value, onChange }: TypeSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as ProjectType)}
      aria-label="切换项目形态"
      className={SELECT_CLASS}
    >
      {ARCHETYPE_ORDER.map((type) => (
        <option key={type} value={type}>
          形态：{ARCHETYPE_BLUEPRINTS[type].label}
        </option>
      ))}
    </select>
  );
}

interface StageControlsProps {
  stage: string;
  stages: ReadonlyArray<ArchetypeStageMeta>;
  nextStage: ArchetypeStageMeta | null;
  onChangeStage: (next: string) => void;
}

function StageControls({ stage, stages, nextStage, onChangeStage }: StageControlsProps) {
  return (
    <>
      <select
        value={stage}
        onChange={(e) => onChangeStage(e.target.value)}
        aria-label="切换项目阶段"
        className={SELECT_CLASS}
      >
        <option value="">阶段：未设置</option>
        {stages.map((item) => (
          <option key={item.id} value={item.id}>
            阶段：{item.label}
          </option>
        ))}
      </select>
      {nextStage && (
        <button
          type="button"
          onClick={() => onChangeStage(nextStage.id)}
          data-testid="studio-advance-stage-btn"
          title={`推进至下一阶段：${nextStage.label}`}
          className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/15"
        >
          推进至「{nextStage.label}」→
        </button>
      )}
    </>
  );
}

interface VcsSelectProps {
  value: 'git' | 'builtin';
  onChange: (next: 'git' | 'builtin') => void;
}

function VcsSelect({ value, onChange }: VcsSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as 'git' | 'builtin')}
      aria-label="切换版本控制模式"
      data-testid="studio-vcs-mode-select"
      className={SELECT_CLASS}
    >
      <option value="git">VCS：Git 仓库</option>
      <option value="builtin">VCS：内置快照</option>
    </select>
  );
}

interface ScaffoldButtonProps {
  scaffolding: boolean;
  onScaffold: () => void;
}

function ScaffoldButton({ scaffolding, onScaffold }: ScaffoldButtonProps) {
  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={onScaffold}
      disabled={scaffolding}
      data-testid="studio-scaffold-btn"
    >
      <Sparkles className="mr-1.5 h-3.5 w-3.5 text-primary" />
      {scaffolding ? '初始化中...' : '一键初始化目录与规范'}
    </Button>
  );
}

interface ProjectControlsProps {
  data: GovernanceData;
  project: GovernanceProject;
  stages: ReadonlyArray<ArchetypeStageMeta>;
  nextStage: ArchetypeStageMeta | null;
}

function ProjectControls({ data, project, stages, nextStage }: ProjectControlsProps) {
  return (
    <div
      className="space-y-3 rounded-lg border border-border p-3"
      data-testid="governance-settings-controls"
    >
      <div className="text-xs font-medium text-foreground">项目类型与版本控制</div>
      <div className="flex flex-wrap items-center gap-2">
        <TypeSelect
          value={data.activeProjectType}
          onChange={(next) => void data.changeProjectType(next)}
        />
        <StageControls
          stage={project.projectStage ?? ''}
          stages={stages}
          nextStage={nextStage}
          onChangeStage={(next) => void data.changeProjectStage(next)}
        />
        <VcsSelect
          value={project.vcsMode === 'git' ? 'git' : 'builtin'}
          onChange={(next) => void data.changeVcsMode(next)}
        />
        <ScaffoldButton scaffolding={data.scaffolding} onScaffold={() => void data.scaffold()} />
      </div>
    </div>
  );
}

function AdvancedWidgets({ project }: { project: GovernanceProject }) {
  return (
    <details
      className="rounded-lg border border-border bg-card/50"
      data-testid="governance-advanced-widgets"
    >
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
        高级项目操作（类型转换 / 快照 / 规则沉淀 / 任务拆解 / Git / Wiki）
      </summary>
      <div className="px-3 pb-3">
        <ProjectOverviewWidgets project={project} />
      </div>
    </details>
  );
}

interface AuditCopyRowProps {
  data: GovernanceData;
  project: GovernanceProject;
  activeTab: string;
}

function AuditCopyRow({ data, project, activeTab }: AuditCopyRowProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const auditOptions = {
    projectId: project.id,
    projectType: data.activeProjectType,
    activeTab,
    milestonesCount: data.milestones.length,
    profileCount: data.profileEntries.length,
    allowedPathsCount: project.allowedPaths?.length ?? 0,
    scaffolding: data.scaffolding,
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        data-testid="project-governance-copy-snapshot"
        onClick={() => {
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(formatProjectGovernanceAuditSnapshot(auditOptions));
        }}
        className="cursor-pointer rounded border border-border px-2 py-1 text-xs text-muted-foreground"
      >
        {copiedSnapshot ? '已复制快照' : '复制治理快照'}
      </span>
      <span
        data-testid="project-governance-copy-json"
        onClick={() => {
          setCopiedJson(true);
          void navigator.clipboard?.writeText(formatProjectGovernanceAuditJson(auditOptions));
        }}
        className="cursor-pointer rounded border border-border px-2 py-1 text-xs text-muted-foreground"
      >
        {copiedJson ? '已复制JSON' : '导出治理JSON'}
      </span>
    </div>
  );
}

export function SettingsSection({ data, activeTab }: SettingsSectionProps) {
  if (!data.project) return null;

  const project = data.project;
  const stages = getArchetypeBlueprint(data.activeProjectType).stages;
  const currentIndex = stages.findIndex((stage) => stage.id === project.projectStage);
  const nextStage =
    currentIndex === -1
      ? stages[0]
      : currentIndex + 1 < stages.length
        ? stages[currentIndex + 1]
        : null;

  return (
    <div className="space-y-4">
      <BootstrapBlock
        project={project}
        projectType={data.activeProjectType}
        onReload={data.reload}
      />
      <PlaybookNote />
      <ProjectControls data={data} project={project} stages={stages} nextStage={nextStage} />
      <AdvancedWidgets project={project} />
      <AuditCopyRow data={data} project={project} activeTab={activeTab} />
    </div>
  );
}
