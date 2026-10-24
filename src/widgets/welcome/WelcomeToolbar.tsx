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
