/**
 * WorkbenchProjectList — workbench-specific project list (Scheme 3 split).
 *
 * Used on the Projects page (/projects route). Differences from
 * SidebarProjectList:
 *  - No SiderSection wrapper, no maxHeight constraint
 *  - Click on project row → toggleExpand (not openProject)
 *  - Expanded row shows sub-sessions + overview + materials panels
 *
 * Data & handlers come from useProjectSectionData hook.
 *
 * Created 2026-10-18 as part of Scheme 3 (ProjectSection split).
 */

import { AlertTriangle, ChevronDown, ChevronRight, Copy, Folder, FolderOpen, MoreHorizontal, Play, Plus } from 'lucide-react';
import type { ReactNode } from 'react';
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ProjectTypeBadge } from '../../../features/project-type/ProjectTypeBadge';
import { getArchetypeBlueprint } from '../../../features/project-type/archetypeBlueprints';
import { projectApi, type ProjectSummary, type ProjectType } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { formatRelativeTime } from '../../../shared/lib/utils';
import { TwoStepDelete } from '../TwoStepDelete';

import {
  FolderMinusIcon,
  MessageDot,
  ProjectMaterialsPanel,
  ProjectOverviewPanel,
} from './ProjectExpandedPanels';
import { useProjectSectionData } from './useProjectSectionData';

interface WorkbenchProjectListProps {
  onOpenSession: (sessionId: string) => void;
}

export function WorkbenchProjectList({ onOpenSession }: WorkbenchProjectListProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const currentSessionId = useStore((s) => s.currentSessionId);
  const [copiedPathId, setCopiedPathId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const data = useProjectSectionData({ onOpenSession });

  const {
    projects,
    busyId,
    missingIds,
    expandedIds,
    subSessions,
    loadingSubIds,
    deletingSessionId,
    dropActive,
    materials,
    loadingMaterials,
    addingMaterial,
    materialDraft,
    removingMaterialId,
    savingAnswerProjectId,
    overviewDraft,
    overviewSavingId,
    setDropActive,
    setMaterialDraft,
    handleDropRegister,
    toggleExpand,
    handleAddProject,
    handleNewChatInProject,
    handleRemoveProject,
    handleDeleteSessionInProject,
    handleOverviewDraftChange,
    handleOverviewSave,
    handleAddMaterial,
    handleRemoveMaterial,
    handleSaveAnswerAsMaterial,
  } = data;

  const renderSubSessions = (project: ProjectSummary) => {
    if (!expandedIds.has(project.id)) return null;
    const sessions = subSessions[project.id];
    if (loadingSubIds.has(project.id) && !sessions) {
      return (
        <div className="px-8 py-1.5 text-ui-2xs text-muted" data-testid="project-sessions-loading">
          {t('sider.project.sessions_loading')}
        </div>
      );
    }
    if (!sessions || sessions.length === 0) {
      return (
        <div className="px-8 py-1.5 text-ui-2xs text-muted" data-testid="project-sessions-empty">
          {t('sider.project.sessions_empty')}
        </div>
      );
    }
    return sessions.map((session) => (
      <div
        key={session.id}
        data-testid="project-session-row"
        aria-current={session.id === currentSessionId ? 'page' : undefined}
        role="button"
        tabIndex={0}
        onClick={() => onOpenSession(session.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onOpenSession(session.id);
          }
        }}
        className="group/sub flex items-center gap-2 ml-5 mr-1.5 px-2 py-1 rounded cursor-pointer hover:bg-bg-hover"
        title={session.title}
      >
        <MessageDot />
        <span className="flex-1 min-w-0 text-ui-sm text-text-secondary truncate">
          {session.title || t('sidebar.new_chat')}
        </span>
        <span className="shrink-0 text-ui-2xs text-muted tabular-nums group-hover/sub:hidden">
          {formatRelativeTime(session.updated_at)}
        </span>
        <div className="hidden group-hover/sub:flex items-center">
          <TwoStepDelete
            data-testid="project-session-delete"
            label={t('sider.project.delete_session')}
            disabled={deletingSessionId === session.id}
            onConfirm={() => void handleDeleteSessionInProject(project, session.id)}
            className="!h-5 !w-5 !px-1 [&>svg]:!h-3 [&>svg]:!w-3"
          />
        </div>
      </div>
    ));
  };

  return (
    <div
      className={`flex flex-col rounded border ${
        dropActive ? 'border-dashed border-primary bg-primary/5' : 'border-transparent'
      }`}
      data-testid="project-drop-zone"
      onDragOver={(e) => {
        e.preventDefault();
        setDropActive(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDropActive(false);
      }}
      onDrop={(e) => void handleDropRegister(e)}
    >
      {/* Section header (no SiderSection wrapper in workbench) */}
      <div className="flex items-center justify-between px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Folder className="w-3.5 h-3.5 text-muted" aria-hidden="true" />
          <span className="text-ui-2xs font-semibold uppercase tracking-wide text-muted">
            {t('sider.section.project')}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleAddProject}
            aria-label={t('sider.project.add')}
            title={t('sider.project.add')}
            data-testid="project-add-button"
            className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {dropActive && (
        <div
          className="px-3 py-2 text-ui-sm text-primary text-center"
          data-testid="project-drop-hint"
        >
          {t('sider.project.drop_hint')}
        </div>
      )}
      {projects.length === 0 ? (
        <div
          className="px-3 py-3 text-ui-sm text-text-muted text-center"
          data-testid="project-empty"
        >
          {t('sider.project.empty')}
        </div>
      ) : (
        projects.map((project) => {
          const missing = missingIds.has(project.id);
          const busy = busyId === project.id;
          const expanded = expandedIds.has(project.id);
          const Chevron = expanded ? ChevronDown : ChevronRight;
          return (
            <div key={project.id} className="flex flex-col">
              <div
                data-testid="project-row"
                role="button"
                tabIndex={0}
                onClick={() => toggleExpand(project)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleExpand(project);
                  }
                }}
                className="group flex items-center gap-1 mx-1.5 px-1.5 py-1.5 rounded cursor-pointer hover:bg-bg-hover"
                title={`${project.name}\n${project.path}`}
              >
                <button
                  type="button"
                  data-testid="project-expand"
                  aria-label={expanded ? t('sider.collapse') : t('sider.expand')}
                  aria-expanded={expanded}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(project);
                  }}
                  className="inline-flex items-center justify-center w-4 h-4 shrink-0 rounded text-muted hover:text-text hover:bg-bg-hover"
                >
                  <Chevron className="w-3 h-3" aria-hidden="true" />
                </button>
                <Folder className="w-3.5 h-3.5 shrink-0 text-muted" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-ui-sm text-text truncate">{project.name}</span>
                    <ProjectTypeBadge
                      type={project.projectType ?? project.detectedType}
                      detected={!project.projectType && Boolean(project.detectedType)}
                    />
                    {project.projectStage && (
                      <span
                        data-testid="project-row-stage-badge"
                        className="shrink-0 rounded border border-border/60 bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-secondary"
                      >
                        {getArchetypeBlueprint(
                          project.projectType ?? project.detectedType ?? 'coding',
                        ).stages.find((s) => s.id === project.projectStage)?.label ??
                          project.projectStage}
                      </span>
                    )}
                    {missing && (
                      <AlertTriangle
                        className="w-3 h-3 shrink-0 text-warning"
                        aria-label={t('sider.project.missing')}
                        data-testid="project-missing-badge"
                      />
                    )}
                  </div>
                  <div className="text-ui-2xs text-muted truncate">{project.path}</div>
                </div>
                {project.sessionCount > 0 && (
                  <span
                    className="shrink-0 text-ui-2xs text-muted tabular-nums"
                    title={t('sider.project.session_count').replace(
                      '{count}',
                      String(project.sessionCount),
                    )}
                  >
                    {project.sessionCount}
                  </span>
                )}
                <div className="hidden group-hover:flex items-center gap-1">
                  {/* Primary action: start or create session */}
                  <button
                    type="button"
                    data-testid="project-primary-action"
                    aria-label={project.sessionCount > 0 ? t('sider.project.new_chat') : t('sider.project.new_chat')}
                    title={project.sessionCount > 0 ? '开始会话' : '新建会话'}
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (project.sessionCount > 0) {
                        // Open most recent session
                        const sessions = subSessions[project.id];
                        if (sessions && sessions.length > 0) {
                          onOpenSession(sessions[0].id);
                        } else {
                          void handleNewChatInProject(project);
                        }
                      } else {
                        void handleNewChatInProject(project);
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded bg-primary/10 border border-primary/30 px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/15 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Play className="w-3 h-3" />
                    {project.sessionCount > 0 ? '会话' : '新建'}
                  </button>

                  {/* ··· More actions menu */}
                  <div className="relative" ref={menuOpenId === project.id ? menuRef : null}>
                    <button
                      type="button"
                      data-testid={`workbench-row-menu-${project.id}`}
                      aria-label="更多操作"
                      aria-expanded={menuOpenId === project.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenuOpenId((prev) => (prev === project.id ? null : project.id));
                      }}
                      className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
                    >
                      <MoreHorizontal className="w-3.5 h-3.5" />
                    </button>
                    {menuOpenId === project.id && (
                      <>
                        {/* Backdrop to close menu on outside click */}
                        <div
                          className="fixed inset-0 z-10"
                          onClick={() => setMenuOpenId(null)}
                        />
                        <div
                          className="absolute right-0 top-full mt-0.5 z-20 min-w-[160px] rounded-md border border-border bg-card shadow-lg py-1"
                          data-testid={`workbench-row-menu-dropdown-${project.id}`}
                        >
                          <MenuItem
                            icon={<FolderOpen className="w-3.5 h-3.5" />}
                            label="项目设置"
                            onClick={() => {
                              setMenuOpenId(null);
                              navigate(`/projects/governance/${project.id}`);
                            }}
                          />
                          <MenuItem
                            label="添加里程碑"
                            onClick={async () => {
                              setMenuOpenId(null);
                              if (typeof projectApi?.createMilestone === 'function') {
                                try {
                                  await projectApi.createMilestone(project.id, {
                                    title: `[项目复核] ${project.name}`,
                                    description: `工作区路径：${project.path}`,
                                    status: 'pending',
                                  });
                                } catch {
                                  // ignore in test/offline mode
                                }
                              }
                            }}
                          />
                          <MenuItem
                            label="添加项目规则"
                            onClick={async () => {
                              setMenuOpenId(null);
                              if (typeof projectApi?.createConstraint === 'function') {
                                try {
                                  await projectApi.createConstraint(project.id, {
                                    category: 'workspace_guard',
                                    content: `[项目边界] ${project.name} (${project.path})`,
                                    triggerPattern: 'always',
                                    priority: 8,
                                  });
                                } catch {
                                  // ignore in test/offline mode
                                }
                              }
                            }}
                          />
                          <MenuItem
                            label="初始化项目目录"
                            onClick={async () => {
                              setMenuOpenId(null);
                              if (typeof projectApi?.scaffold === 'function') {
                                try {
                                  await projectApi.scaffold(project.id, {
                                    projectType: (project.projectType ?? project.detectedType ?? 'coding') as ProjectType,
                                    createDirectories: true,
                                    createSageMd: true,
                                    importDefaultConstraints: true,
                                    seedDefaultMilestones: true,
                                  });
                                } catch {
                                  // ignore in test/offline mode
                                }
                              }
                            }}
                          />
                          <MenuItem
                            icon={<Copy className="w-3.5 h-3.5" />}
                            label={copiedPathId === project.id ? '已复制' : '复制路径'}
                            onClick={async () => {
                              setMenuOpenId(null);
                              try {
                                await navigator.clipboard?.writeText(project.path);
                                setCopiedPathId(project.id);
                                setTimeout(() => setCopiedPathId(null), 1500);
                              } catch {
                                // ignore in test/offline mode
                              }
                            }}
                          />
                          <div className="border-t border-border my-1" />
                          <MenuItem
                            icon={<FolderMinusIcon />}
                            label="移除项目"
                            destructive
                            onClick={async () => {
                              setMenuOpenId(null);
                              await handleRemoveProject(project);
                            }}
                          />
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
              {renderSubSessions(project)}
              {expandedIds.has(project.id) && (
                <>
                  <ProjectOverviewPanel
                    project={project}
                    draft={overviewDraft[project.id]}
                    saving={overviewSavingId === project.id}
                    onSave={(p) => void handleOverviewSave(p)}
                    onChange={handleOverviewDraftChange}
                  />
                  <ProjectMaterialsPanel
                    project={project}
                    list={materials[project.id]}
                    isLoading={loadingMaterials.has(project.id) && !materials[project.id]}
                    isAdding={addingMaterial.has(project.id)}
                    draftText={materialDraft[project.id] ?? ''}
                    currentSessionId={currentSessionId}
                    savingAnswer={savingAnswerProjectId === project.id}
                    removingMaterialId={removingMaterialId}
                    onSaveAnswer={(p) => void handleSaveAnswerAsMaterial(p)}
                    onRemoveMaterial={(p, mid) => void handleRemoveMaterial(p, mid)}
                    onDraftChange={(pid, text) =>
                      setMaterialDraft((prev) => ({ ...prev, [pid]: text }))
                    }
                    onAddMaterial={(p) => void handleAddMaterial(p)}
                  />
                </>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

/* ── MenuItem helper ─────────────────────────────────────────────── */

interface MenuItemProps {
  label: string;
  icon?: ReactNode;
  destructive?: boolean;
  onClick: () => void;
}

function MenuItem({ label, icon, destructive, onClick }: MenuItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-ui-2xs transition-colors ${
        destructive
          ? 'text-destructive hover:bg-destructive/10'
          : 'text-foreground hover:bg-muted'
      }`}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {label}
    </button>
  );
}
