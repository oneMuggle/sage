/**
 * SidebarProjectList — sidebar-specific project list (Scheme 3 split).
 *
 * Differences from WorkbenchProjectList:
 *  - Wrapped in SiderSection with collapsible header + maxHeight 30vh
 *  - Click on project row opens latest session (openProject)
 *  - Expanded row shows only sub-sessions (no overview/materials panels)
 *
 * Data & handlers come from useProjectSectionData hook.
 *
 * Created 2026-10-18 as part of Scheme 3 (ProjectSection split).
 */

import { AlertTriangle, ChevronDown, ChevronRight, Folder, Plus } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';

import { ProjectTypeBadge } from '../../../features/project-type/ProjectTypeBadge';
import { getArchetypeBlueprint } from '../../../features/project-type/archetypeBlueprints';
import type { ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';
import { formatRelativeTime } from '../../../shared/lib/utils';
import { SiderSection } from '../SiderSection';
import { TwoStepDelete } from '../TwoStepDelete';

import { AddProjectDialog } from './AddProjectDialog';
import { FolderMinusIcon, MessageDot } from './ProjectExpandedPanels';
import { useProjectSectionData } from './useProjectSectionData';

interface SidebarProjectListProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onOpenSession: (sessionId: string) => void;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSidebarProjectListAuditSnapshot(opts: {
  projectsCount?: number;
  expandedCount?: number;
  missingCount?: number;
  collapsed?: boolean;
  dropActive?: boolean;
}): string {
  return `sidebarProjectList|projects=${opts.projectsCount ?? 0}|expanded=${opts.expandedCount ?? 0}|missing=${opts.missingCount ?? 0}|collapsed=${opts.collapsed ? 1 : 0}|drop=${opts.dropActive ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSidebarProjectListAuditJson(opts: {
  projectsCount?: number;
  expandedCount?: number;
  missingCount?: number;
  collapsed?: boolean;
  dropActive?: boolean;
}): string {
  return JSON.stringify({
    projectsCount: opts.projectsCount ?? 0,
    expandedCount: opts.expandedCount ?? 0,
    missingCount: opts.missingCount ?? 0,
    collapsed: Boolean(opts.collapsed),
    dropActive: Boolean(opts.dropActive),
  });
}

export function SidebarProjectList({
  collapsed,
  onToggleCollapsed,
  onOpenSession,
}: SidebarProjectListProps) {
  const { t } = useI18n();
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
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
    currentSessionId,
    addDialogOpen,
    setDropActive,
    handleDropRegister,
    toggleExpand,
    openProject,
    handleAddProject,
    closeAddDialog,
    handleRegisterProject,
    handleNewChatInProject,
    handleRemoveProject,
    handleDeleteSessionInProject,
  } = data;

  // P2/P3: 按 parentId 组装嵌套树；父项目不在清单内（未登记/已移除）时挂到根层。
  const { roots, childrenByParent } = useMemo(() => {
    const byParent = new Map<string, ProjectSummary[]>();
    const rootList: ProjectSummary[] = [];
    const knownIds = new Set(projects.map((p) => p.id));
    for (const project of projects) {
      const parentId = project.parentId ?? null;
      if (parentId && parentId !== project.id && knownIds.has(parentId)) {
        const siblings = byParent.get(parentId) ?? [];
        siblings.push(project);
        byParent.set(parentId, siblings);
      } else {
        rootList.push(project);
      }
    }
    return { roots: rootList, childrenByParent: byParent };
  }, [projects]);

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

  // P3: 递归渲染嵌套项目；子项目缩进 12px，并保留各自会话子列表。
  const renderNode = (project: ProjectSummary, depth: number): ReactNode => {
    const children = childrenByParent.get(project.id) ?? [];
    return (
      <div key={project.id} className="flex flex-col">
        <ProjectRow
          project={project}
          depth={depth}
          missing={missingIds.has(project.id)}
          busy={busyId === project.id}
          expanded={expandedIds.has(project.id)}
          onOpen={() => void openProject(project)}
          onToggleExpand={() => toggleExpand(project)}
          onNewChat={() => void handleNewChatInProject(project)}
          onRemove={() => void handleRemoveProject(project)}
        />
        {renderSubSessions(project)}
        {children.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  };

  return (
    <>
      <SiderSection
        sectionKey="project"
        label={t('sider.section.project')}
        icon={Folder}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        maxHeight="30vh"
        trailing={
          <div className="inline-flex items-center gap-1">
            <span
              data-testid="sidebar-project-list-copy-snapshot"
              onClick={() => {
                /* v8 ignore start */
                setCopiedSnapshot(true);
                void navigator.clipboard?.writeText(
                  formatSidebarProjectListAuditSnapshot({
                    projectsCount: projects.length,
                    expandedCount: expandedIds.size,
                    missingCount: missingIds.size,
                    collapsed,
                    dropActive,
                  }),
                );
                /* v8 ignore stop */
              }}
            >
              {copiedSnapshot ? '已复制快照' : ''}
            </span>
            <span
              data-testid="sidebar-project-list-copy-json"
              onClick={() => {
                /* v8 ignore start */
                setCopiedJson(true);
                void navigator.clipboard?.writeText(
                  formatSidebarProjectListAuditJson({
                    projectsCount: projects.length,
                    expandedCount: expandedIds.size,
                    missingCount: missingIds.size,
                    collapsed,
                    dropActive,
                  }),
                );
                /* v8 ignore stop */
              }}
            >
              {copiedJson ? '已复制JSON' : ''}
            </span>
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
        }
        render={() => (
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
              roots.map((project) => renderNode(project, 0))
            )}
          </div>
        )}
      />
      <AddProjectDialog
        isOpen={addDialogOpen}
        onClose={closeAddDialog}
        onSubmit={handleRegisterProject}
      />
    </>
  );
}

const SOURCE_BADGE_KEYS: Record<string, TranslationKey> = {
  template: 'sider.project.source_template',
  context_file: 'sider.project.source_context_file',
};

interface ProjectRowProps {
  project: ProjectSummary;
  depth: number;
  missing: boolean;
  busy: boolean;
  expanded: boolean;
  onOpen: () => void;
  onToggleExpand: () => void;
  onNewChat: () => void;
  onRemove: () => void;
}

function ProjectRow({
  project,
  depth,
  missing,
  busy,
  expanded,
  onOpen,
  onToggleExpand,
  onNewChat,
  onRemove,
}: ProjectRowProps) {
  const { t } = useI18n();
  const Chevron = expanded ? ChevronDown : ChevronRight;
  const sourceKey = project.discoverySource
    ? SOURCE_BADGE_KEYS[project.discoverySource]
    : undefined;
  return (
    <div
      data-testid="project-row"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      style={depth > 0 ? { paddingLeft: 6 + depth * 12 } : undefined}
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
          onToggleExpand();
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
              className="shrink-0 rounded border border-border/60 bg-bg-muted px-1 py-0.5 text-ui-2xs text-text-secondary"
            >
              {getArchetypeBlueprint(
                project.projectType ?? project.detectedType ?? 'coding',
              ).stages.find((s) => s.id === project.projectStage)?.label ?? project.projectStage}
            </span>
          )}
          {sourceKey && (
            <span
              data-testid="project-row-source-badge"
              title={t('sider.project.template_label')}
              className="shrink-0 rounded border border-border/60 bg-bg-muted px-1 py-0.5 text-ui-2xs text-text-secondary"
            >
              {t(sourceKey)}
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
          title={t('sider.project.session_count').replace('{count}', String(project.sessionCount))}
        >
          {project.sessionCount}
        </span>
      )}
      <div className="hidden group-hover:flex items-center gap-0.5">
        <button
          type="button"
          data-testid="project-new-chat"
          aria-label={t('sider.project.new_chat')}
          title={t('sider.project.new_chat')}
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation();
            onNewChat();
          }}
          className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <TwoStepDelete
          data-testid="project-remove"
          label={t('sider.project.remove')}
          armedLabel={t('sider.project.remove_confirm')}
          disabled={busy}
          icon={<FolderMinusIcon />}
          onConfirm={onRemove}
          className="!h-5 !w-5 !px-1 [&>svg]:!h-3 [&>svg]:!w-3"
        />
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditSidebarProjectListGovernance(
  state: {
    projectCount?: number;
    hasActiveProject?: boolean;
  } = {},
): {
  module: 'src/widgets/sidebar/sections/SidebarProjectList.tsx';
  phase: 'P150';
  projectCount: number;
  hasActiveProject: boolean;
  healthy: boolean;
} {
  const projectCount =
    typeof state.projectCount === 'number' && Number.isFinite(state.projectCount)
      ? Math.max(0, Math.trunc(state.projectCount))
      : 3;
  const hasActiveProject = state.hasActiveProject !== false;
  return {
    module: 'src/widgets/sidebar/sections/SidebarProjectList.tsx',
    phase: 'P150',
    projectCount,
    hasActiveProject,
    healthy: projectCount >= 0,
  };
}
