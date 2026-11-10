import { Sparkles } from 'lucide-react';
import { useState } from 'react';

import {
  ProjectBootstrapPanel,
  ProjectOverviewWidgets,
  WikiGenerationPanel,
} from '../../../features/project-type';
import {
  StudioAllowedPathsTabPanel,
  StudioCharterTabPanel,
  StudioMetadataPanel,
} from '../../../features/project-type/StudioMaterialsAndProfilePanels';
import {
  ARCHETYPE_BLUEPRINTS,
  ARCHETYPE_ORDER,
  getArchetypeBlueprint,
  type ArchetypeStageMeta,
} from '../../../features/project-type/archetypeBlueprints';
import type { ProjectType } from '../../../shared/api';
import { Button } from '../../../shared/ui/Button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../shared/ui/Select/Select';
import {
  formatProjectGovernanceAuditJson,
  formatProjectGovernanceAuditSnapshot,
} from '../governanceAudit';
import type { GovernanceData } from '../useGovernanceProject';

type GovernanceProject = NonNullable<GovernanceData['project']>;

/** Radix Select 不接受空字符串作为 item value，所以「未设置」用占位值替代。 */
const NO_STAGE_VALUE = '__none__';

const SELECT_TRIGGER_CLASS = 'h-8 w-auto min-w-[9rem] px-2 text-sm';

export interface SettingsSectionProps {
  data: GovernanceData;
  activeTab: string;
  onStartSession: () => void;
}

function SettingsSectionHeading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-sm font-semibold text-foreground">{title}</div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function ProjectControls({
  data,
  project,
  stages,
  nextStage,
}: {
  data: GovernanceData;
  project: GovernanceProject;
  stages: ReadonlyArray<ArchetypeStageMeta>;
  nextStage: ArchetypeStageMeta | null;
}) {
  const stageLabel = stages.find((stage) => stage.id === project.projectStage)?.label ?? '未设置';

  return (
    <div
      className="rounded-lg border border-border bg-card p-3"
      data-testid="governance-settings-controls"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={data.activeProjectType}
          onValueChange={(value) => void data.changeProjectType(value as ProjectType)}
        >
          <SelectTrigger aria-label="切换项目类型" className={SELECT_TRIGGER_CLASS}>
            <SelectValue>
              项目类型：{ARCHETYPE_BLUEPRINTS[data.activeProjectType].label}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {ARCHETYPE_ORDER.map((type) => (
              <SelectItem key={type} value={type}>
                项目类型：{ARCHETYPE_BLUEPRINTS[type].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={project.projectStage ?? NO_STAGE_VALUE}
          onValueChange={(value) =>
            void data.changeProjectStage(value === NO_STAGE_VALUE ? '' : value)
          }
        >
          <SelectTrigger aria-label="切换项目阶段" className={SELECT_TRIGGER_CLASS}>
            <SelectValue>阶段：{stageLabel}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_STAGE_VALUE}>阶段：未设置</SelectItem>
            {stages.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                阶段：{item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {nextStage && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void data.changeProjectStage(nextStage.id)}
            data-testid="studio-advance-stage-btn"
            title={`推进至下一阶段：${nextStage.label}`}
          >
            推进至「{nextStage.label}」→
          </Button>
        )}
        <Select
          value={project.vcsMode === 'git' ? 'git' : 'builtin'}
          onValueChange={(value) => void data.changeVcsMode(value as 'git' | 'builtin')}
        >
          <SelectTrigger
            aria-label="切换版本控制模式"
            data-testid="studio-vcs-mode-select"
            className={SELECT_TRIGGER_CLASS}
          >
            <SelectValue>
              版本控制：{project.vcsMode === 'git' ? 'Git 仓库' : '内置快照'}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="git">版本控制：Git 仓库</SelectItem>
            <SelectItem value="builtin">版本控制：内置快照</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

function ScaffoldButton({
  scaffolding,
  onScaffold,
}: {
  scaffolding: boolean;
  onScaffold: () => void;
}) {
  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={onScaffold}
      disabled={scaffolding}
      data-testid="studio-scaffold-btn"
    >
      <Sparkles className="mr-1.5 h-3.5 w-3.5 text-primary" />
      {scaffolding ? '初始化中...' : '初始化目录与规范'}
    </Button>
  );
}

function AuditCopyRow({
  data,
  project,
  activeTab,
}: {
  data: GovernanceData;
  project: GovernanceProject;
  activeTab: string;
}) {
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
      <Button
        size="sm"
        variant="ghost"
        data-testid="project-governance-copy-snapshot"
        onClick={() => {
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(formatProjectGovernanceAuditSnapshot(auditOptions));
        }}
      >
        {copiedSnapshot ? '已复制快照' : '复制项目状态摘要'}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        data-testid="project-governance-copy-json"
        onClick={() => {
          setCopiedJson(true);
          void navigator.clipboard?.writeText(formatProjectGovernanceAuditJson(auditOptions));
        }}
      >
        {copiedJson ? '已复制JSON' : '复制项目状态 JSON'}
      </Button>
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
    <div className="space-y-5" data-testid="governance-settings">
      {/* 1. 基本信息（项目描述 + 会话指令） */}
      <section className="space-y-2">
        <SettingsSectionHeading title="基本信息" hint="项目描述与会话指令会作为每次会话的背景" />
        <StudioMetadataPanel
          projectId={project.id}
          projectType={data.activeProjectType}
          initialDescription={project.description}
          initialInstructions={project.instructions}
          onMetadataUpdated={() => void data.reload()}
        />
      </section>

      {/* 2. 项目总纲（SAGE.md，折叠） */}
      <section className="space-y-2">
        <SettingsSectionHeading
          title="项目总纲（SAGE.md）"
          hint="项目最高优先级的背景说明，通常由 AI 初始化生成或手工维护"
        />
        <details className="rounded-lg border border-border bg-card">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
            编辑项目总纲（SAGE.md）
          </summary>
          <div className="px-3 pb-3">
            <StudioCharterTabPanel projectId={project.id} projectPath={project.path} />
          </div>
        </details>
      </section>

      {/* 3. AI 初始化（默认不自动扫描） */}
      <section className="space-y-2">
        <SettingsSectionHeading
          title="AI 初始化"
          hint="按需分析项目并生成建议；应用前需逐条勾选，不会自动修改文件"
        />
        <ProjectBootstrapPanel projectId={project.id} />
      </section>

      {/* 4. 项目类型与版本控制 */}
      <section className="space-y-2">
        <SettingsSectionHeading title="项目类型与版本控制" />
        <ProjectControls data={data} project={project} stages={stages} nextStage={nextStage} />
      </section>

      {/* 5. 高级（默认折叠） */}
      <details
        className="rounded-lg border border-border bg-card/50"
        data-testid="governance-settings-advanced"
      >
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
          高级设置（目录初始化 · 外部文件夹 · Wiki · 快照与导出台账）
        </summary>
        <div className="space-y-3 px-3 pb-3">
          <div className="space-y-2">
            <SettingsSectionHeading title="目录初始化" hint="按项目类型生成目录骨架与规范模板" />
            <ScaffoldButton
              scaffolding={data.scaffolding}
              onScaffold={() => void data.scaffold()}
            />
          </div>
          <div className="space-y-2" data-testid="settings-allowed-paths">
            <SettingsSectionHeading
              title="外部文件夹（只读）"
              hint="允许 AI 读取项目目录之外的文件，不会修改它们"
            />
            <StudioAllowedPathsTabPanel
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
          </div>
          <div data-testid="governance-advanced-widgets">
            <ProjectOverviewWidgets project={project} />
          </div>
          <div className="space-y-2">
            <SettingsSectionHeading
              title="项目 Wiki"
              hint="按需生成项目文档站；生成前会先给草稿预览，确认后才写入"
            />
            <WikiGenerationPanel projectId={project.id} projectType={data.activeProjectType} />
          </div>
          <AuditCopyRow data={data} project={project} activeTab={activeTab} />
        </div>
      </details>
    </div>
  );
}
