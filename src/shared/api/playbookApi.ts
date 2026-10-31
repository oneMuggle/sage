/**
 * 项目规程 API 客户端（2026-10-31）。
 *
 * 类型与后端 `/api/v1/playbooks`、`/api/v1/projects/{id}/playbook` 的
 * snake_case 响应保持一致，避免额外映射层。
 */

import { invoke } from './desktopInvoke';

export interface PlaybookMatch {
  globs: string[];
  min_bytes: number;
  min_count: number;
  max_age_days?: number | null;
}

export interface PlaybookContentCheck {
  id: string;
  label: string;
  type: string;
  keywords: string[];
  llm_prompt?: string;
}

export interface PlaybookArtifactSpec {
  id: string;
  label: string;
  required: boolean;
  required_when?: string | null;
  target_dir?: string | null;
  match: PlaybookMatch;
  content_checks: PlaybookContentCheck[];
  missing_action?: PlaybookAction | null;
}

export interface PlaybookStageSpec {
  id: string;
  label: string;
  order: number;
  objective: string;
  artifacts: PlaybookArtifactSpec[];
  exit_criteria: Array<Record<string, unknown>>;
  rules: Array<Record<string, unknown>>;
  recommended_milestones: Array<Record<string, unknown>>;
}

export interface PlaybookSpec {
  schema_version: string;
  id: string;
  name: string;
  description: string;
  applies_to: { project_types: string[]; sub_types: string[] };
  directory_layout: Array<{ path: string; required: boolean; purpose: string }>;
  stages: PlaybookStageSpec[];
  global_rules: Array<Record<string, unknown>>;
  todos: Array<Record<string, unknown>>;
  ai_guidance: Record<string, unknown>;
  meta: Record<string, unknown>;
}

export interface PlaybookSummary {
  id: string;
  name: string;
  description: string;
  project_types: string[];
  sub_types: string[];
  stage_count: number;
  directories: string[];
}

export interface PlaybookAction {
  type: string;
  payload?: Record<string, unknown>;
}

export interface PlaybookState {
  current_stage?: string | null;
  stage_history?: Array<{
    from?: string | null;
    to: string;
    at: number;
    source?: string;
  }>;
  waivers?: string[];
  manual_done?: string[];
}

export interface PlaybookArtifactAudit {
  id: string;
  label: string;
  required: boolean;
  status: 'present' | 'missing' | 'stale' | 'optional' | 'waived';
  target_dir?: string | null;
  evidence: {
    matches: string[];
    misplaced: string[];
    count: number;
    latest_mtime: number | null;
    globs: string[];
  };
  checks: Array<{
    id: string;
    label: string;
    type: string;
    status: string;
    keywords: string[];
    hits: string[];
  }>;
  missing_action?: PlaybookAction | null;
}

export interface PlaybookStageAudit {
  id: string;
  label: string;
  order: number;
  objective: string;
  progress: number;
  required_total: number;
  required_done: number;
  remaining: Array<{
    id: string;
    label: string;
    missing_action?: PlaybookAction | null;
  }>;
  artifacts: PlaybookArtifactAudit[];
  exit_criteria: Array<{
    id: string | null;
    label: string;
    type: string;
    status: string;
  }>;
}

export interface PlaybookAudit {
  playbook: { id?: string; name?: string };
  current_stage: string | null;
  detected_stage: {
    id: string | null;
    confidence: number;
    evidence: string[];
  };
  stages: PlaybookStageAudit[];
  classification_suggestions: Array<{
    from: string;
    to: string;
    artifact_id: string;
    label: string;
    stage_id: string;
    reason: string;
  }>;
  overall: {
    required_total: number;
    required_done: number;
    progress: number;
  };
  scanned_at: number;
  llm_available?: boolean;
}

export interface PlaybookCurrent {
  bound: boolean;
  playbook?: PlaybookSpec | null;
  source?: string | null;
  version?: number | null;
  spec_hash?: string | null;
  state: PlaybookState;
  suggested?: PlaybookSummary | null;
  audit?: PlaybookAudit | null;
}

export interface PlaybookActionsResult {
  applied: string[];
  skipped: string[];
  errors: Array<{ item: string; message: string }>;
  checkpoint_created: boolean;
  audit?: PlaybookAudit | null;
}

export interface PlaybookExportResult {
  format: 'json' | 'md' | 'agents';
  filename: string;
  content: unknown;
}

export interface PlaybookWikiExportResult {
  path: string;
  created: boolean;
  updated: boolean;
}

export interface PlaybookVersion {
  version: number;
  source: string;
  spec_hash: string;
  created_at: number;
  active: boolean;
}

<<<<<<< HEAD
=======
export interface PlaybookLibraryItem {
  id: string;
  name: string;
  source: string;
  spec_hash: string;
  created_at: number;
  stage_count: number;
  directories: string[];
}

>>>>>>> origin/main
export interface PlaybookStatePatch {
  waivers?: string[];
  manual_done?: string[];
  conditions?: Record<string, unknown>;
}

export interface PlaybookImportPreview {
  playbook: PlaybookSpec;
  scaffold: {
    include: boolean;
    directories: string[];
    documents: Array<Record<string, unknown>>;
  };
  diff: Record<string, unknown>;
}

export interface PlaybookAuthorPreview {
  playbook: PlaybookSpec;
  rationale: string;
  llm_available: boolean;
  source: string;
}

export interface PlaybookBindPayload {
  playbookId?: string;
<<<<<<< HEAD
=======
  libraryId?: string;
>>>>>>> origin/main
  spec?: PlaybookSpec;
  source?: string;
}

export const playbookApi = {
  async listBuiltin(): Promise<PlaybookSummary[]> {
    const response = await invoke<{ playbooks: PlaybookSummary[] }>('playbooks_builtin_list');
    return response.playbooks ?? [];
  },

  async getBuiltin(playbookId: string): Promise<PlaybookSpec> {
    const response = await invoke<{ playbook: PlaybookSpec }>('playbooks_builtin_get', {
      playbookId,
    });
    return response.playbook;
  },

  async getCurrent(projectId: string): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_get_current', { projectId });
  },

  async bind(projectId: string, payload: PlaybookBindPayload): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_bind', {
      projectId,
      playbookId: payload.playbookId,
<<<<<<< HEAD
=======
      libraryId: payload.libraryId,
>>>>>>> origin/main
      spec: payload.spec,
      source: payload.source,
    });
  },

  async audit(projectId: string): Promise<PlaybookAudit> {
    return invoke<PlaybookAudit>('playbook_audit', { projectId });
  },

  async auditAi(projectId: string, useLlm = true): Promise<PlaybookAudit> {
    return invoke<PlaybookAudit>('playbook_audit_ai', { projectId, useLlm });
  },

  async authorPreview(
    projectId: string,
    answers: Record<string, unknown> = {},
    useLlm = true,
  ): Promise<PlaybookAuthorPreview> {
    return invoke<PlaybookAuthorPreview>('playbook_author_preview', {
      projectId,
      answers,
      useLlm,
    });
  },

  async confirmStage(projectId: string, stageId: string): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_stage_confirm', {
      projectId,
      stageId,
    });
  },

  async applyActions(projectId: string, actions: PlaybookAction[]): Promise<PlaybookActionsResult> {
    return invoke<PlaybookActionsResult>('playbook_actions_apply', {
      projectId,
      actions,
    });
  },

  async exportPlaybook(
    projectId: string,
    format: 'json' | 'md' | 'agents' = 'json',
    includeScaffold = true,
  ): Promise<PlaybookExportResult> {
    return invoke<PlaybookExportResult>('playbook_export', {
      projectId,
      format,
      includeScaffold,
    });
  },

  async exportToWiki(projectId: string): Promise<PlaybookWikiExportResult> {
    return invoke<PlaybookWikiExportResult>('playbook_wiki_export', { projectId });
  },

  async updateState(
    projectId: string,
    patch: PlaybookStatePatch,
  ): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_state_update', {
      projectId,
      ...patch,
    });
  },

  async unbind(projectId: string): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_unbind', { projectId });
  },

  async listVersions(projectId: string): Promise<PlaybookVersion[]> {
    const response = await invoke<{ versions: PlaybookVersion[] }>(
      'playbook_versions',
      { projectId },
    );
    return response.versions ?? [];
  },

  async cleanupRules(projectId: string): Promise<number> {
    const response = await invoke<{ removed: number }>('playbook_rules_cleanup', {
      projectId,
    });
    return response.removed;
  },

  async importPreview(
    envelope: Record<string, unknown>,
    projectId?: string,
  ): Promise<PlaybookImportPreview> {
    return invoke<PlaybookImportPreview>('playbook_import_preview', {
      envelope,
      projectId,
    });
  },

  async importPlaybook(
    envelope: Record<string, unknown>,
    projectId: string,
    conflict: 'replace' | 'merge' | 'save_as_new' = 'save_as_new',
<<<<<<< HEAD
=======
    saveToLibrary = false,
>>>>>>> origin/main
  ): Promise<PlaybookCurrent> {
    return invoke<PlaybookCurrent>('playbook_import', {
      envelope,
      projectId,
      conflict,
<<<<<<< HEAD
    });
  },
=======
      saveToLibrary,
    });
  },

  async listLibrary(): Promise<PlaybookLibraryItem[]> {
    const response = await invoke<{ items: PlaybookLibraryItem[] }>(
      'playbooks_library_list',
    );
    return response.items ?? [];
  },

  async saveLibrary(
    envelope: Record<string, unknown>,
    source = 'imported',
  ): Promise<PlaybookLibraryItem> {
    const response = await invoke<{ item: PlaybookLibraryItem }>(
      'playbooks_library_save',
      { envelope, source },
    );
    return response.item;
  },

  async deleteLibrary(libraryId: string): Promise<void> {
    await invoke<{ removed: boolean }>('playbooks_library_delete', { libraryId });
  },
>>>>>>> origin/main
};
