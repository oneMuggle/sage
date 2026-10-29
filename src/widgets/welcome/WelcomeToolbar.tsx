import type { BranchEntry, SessionWorktree } from '../../shared/api/worktreeApi';

import { ModelPicker, type ModelOption } from './ModelPicker';
import { ProjectPicker, type ProjectOption } from './ProjectPicker';
import { WorktreePicker, type WorktreeMode, type WorktreePickerValue } from './WorktreePicker';

export interface WelcomeToolbarProps {
  // Project
  projectId: string | null;
  onProjectChange: (projectId: string | null) => void;
  projects: ProjectOption[];

  // Model
  modelId: string | null;
  onModelChange: (modelId: string | null) => void;
  models: ModelOption[];
  globalModelId: string | null;
  /** Task 8: 仅当全局 routing.mode === 'auto' 时透传，渲染「自动路由」选项。 */
  autoAvailable?: boolean;

  // Worktree
  worktreeMode: WorktreeMode;
  worktreeBranch: string | null;
  worktreeId: string | null;
  onWorktreeChange: (value: WorktreePickerValue) => void;
  branches: BranchEntry[];
  worktrees: SessionWorktree[];
}

export function WelcomeToolbar({
  projectId,
  onProjectChange,
  projects,
  modelId,
  onModelChange,
  models,
  globalModelId,
  autoAvailable = false,
  worktreeMode,
  worktreeBranch,
  worktreeId,
  onWorktreeChange,
  branches,
  worktrees,
}: WelcomeToolbarProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-t border-border bg-surface">
      <ProjectPicker value={projectId} onChange={onProjectChange} projects={projects} />
      <ModelPicker
        value={modelId}
        onChange={onModelChange}
        models={models}
        globalModelId={globalModelId}
        autoAvailable={autoAvailable}
      />
      <WorktreePicker
        mode={worktreeMode}
        branch={worktreeBranch}
        worktreeId={worktreeId}
        onChange={onWorktreeChange}
        branches={branches}
        worktrees={worktrees}
      />
    </div>
  );
}
