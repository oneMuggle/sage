/**
 * ProjectSection — 项目模块 P1 (2026-09-13) 侧边栏入口；P2 (2026-09-13)
 * 增加行内会话子列表。
 *
 * 对标主流 AI 工具的"最近项目"概念（Cursor Recent Workspaces / Claude Code
 * 项目 → 会话归属）：列出用户登记的工作目录，点击即进入该项目 —— 后端
 * 复用项目最近的活跃会话（无则新建并绑定项目目录），前端切换过去。
 *
 * 行内操作（hover 显现）：
 *  - +：在该项目下显式新建一个绑定会话；
 *  - TwoStepDelete：从清单移除（只删注册行，不动磁盘与任何会话）。
 *
 * P2 行展开：chevron 展开后懒加载该项目的未归档会话（≤20 条），子行
 * 轻量自绘（title + 相对时间 + 消息数）——刻意不复用 SessionItem（其
 * 订阅 5 个 store 且带全套会话操作，嵌套场景过重）；子行点击走
 * onOpenSession 与会话列表同一入口。
 *
 * 目录在磁盘上消失时 open 返回 410 project_path_missing：该行标记"目录
 * 不存在"，仍可点击重试或移除。数据经 projectApi（invoke → IPC → 后端
 * /api/v1/projects），刷新走 store.loadSessions() 保证会话区即时同步。
 */

import { AlertTriangle, ChevronDown, ChevronRight, Folder, Plus } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { InvokeError } from '../../../shared/api/desktopInvoke';
import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { sessionApi } from '../../../shared/api/sessionApi';
import { useI18n } from '../../../shared/lib/i18n';
import { useStore, type Session } from '../../../shared/lib/store';
import { formatRelativeTime } from '../../../shared/lib/utils';
import { SiderSection } from '../SiderSection';
import { TwoStepDelete } from '../TwoStepDelete';

interface ProjectSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Sidebar 统一的会话切换回调：setCurrentSessionId + 按需 navigate('/chat') */
  onOpenSession: (sessionId: string) => void;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

/** 后端"目录已消失"的稳定信号（open → 410 project_path_missing） */
function isPathMissingError(err: unknown): boolean {
  return (err as InvokeError)?.status_code === 410;
}

/** P4: 会话数量变化触发的项目清单刷新防抖（ms）——吞掉连续增删的抖动 */
const PROJECT_REFRESH_DEBOUNCE_MS = 400;

export function ProjectSection({
  collapsed,
  onToggleCollapsed,
  onOpenSession,
}: ProjectSectionProps) {
  const { t } = useI18n();
  const loadSessions = useStore((s) => s.loadSessions);

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  /** open 命中 410 的项目 id：行内显示"目录不存在"标记 */
  const [missingIds, setMissingIds] = useState<Set<string>>(new Set());
  // ===== P2: 行展开会话子列表 =====
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [subSessions, setSubSessions] = useState<Record<string, Session[]>>({});
  const [loadingSubIds, setLoadingSubIds] = useState<Set<string>>(new Set());
  // ===== P4: 子行会话删除 =====
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await projectApi.list());
    } catch (err) {
      toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅首启加载一次
  }, []);

  const clearMissing = useCallback((id: string) => {
    setMissingIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  /** P2: 拉取（或刷新）某项目的会话子列表；失败仅 toast 不改展开态。 */
  const refreshSubSessions = useCallback(
    async (projectId: string) => {
      setLoadingSubIds((prev) => new Set(prev).add(projectId));
      try {
        const sessions = await projectApi.listSessions(projectId);
        setSubSessions((prev) => ({ ...prev, [projectId]: sessions }));
      } catch (err) {
        toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
      } finally {
        setLoadingSubIds((prev) => {
          const next = new Set(prev);
          next.delete(projectId);
          return next;
        });
      }
    },
    [t],
  );

  // P4: 任意来源的会话增删（会话区删除、对话产生新会话等）→ 防抖刷新
  // 项目清单与已展开子列表。session_count 是后端聚合查询，单一事实源
  // 不本地推算；以 store sessions 长度变化为触发信号。
  const sessionsCount = useStore((s) => s.sessions.length);
  const prevSessionsCountRef = useRef(sessionsCount);
  useEffect(() => {
    if (prevSessionsCountRef.current === sessionsCount) return;
    prevSessionsCountRef.current = sessionsCount;
    const timer = setTimeout(() => {
      void refresh();
      expandedIds.forEach((id) => void refreshSubSessions(id));
    }, PROJECT_REFRESH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [sessionsCount, expandedIds, refresh, refreshSubSessions]);

  /** P2: 展开/收起；首次展开时懒加载。 */
  const toggleExpand = useCallback(
    (project: ProjectSummary) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(project.id)) {
          next.delete(project.id);
        } else {
          next.add(project.id);
        }
        return next;
      });
      if (!expandedIds.has(project.id) && !subSessions[project.id]) {
        void refreshSubSessions(project.id);
      }
    },
    [expandedIds, refreshSubSessions, subSessions],
  );

  const openProject = useCallback(
    async (project: ProjectSummary) => {
      if (busyId) return;
      setBusyId(project.id);
      try {
        const { session } = await projectApi.open(project.id);
        clearMissing(project.id);
        await loadSessions();
        onOpenSession(session.id);
        void refresh();
        if (expandedIds.has(project.id)) void refreshSubSessions(project.id);
      } catch (err) {
        if (isPathMissingError(err)) {
          setMissingIds((prev) => new Set(prev).add(project.id));
          toast.error(t('sider.project.missing'));
        } else {
          toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
        }
      } finally {
        setBusyId(null);
      }
    },
    [
      busyId,
      clearMissing,
      expandedIds,
      loadSessions,
      onOpenSession,
      refresh,
      refreshSubSessions,
      t,
    ],
  );

  const handleAddProject = useCallback(async () => {
    const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
    if (!api) {
      toast.error(t('sider.project.add_failed').replace('{message}', 'IPC 桥接不可用'));
      return;
    }
    try {
      const picked = await api.selectDirectory({ intent: 'open' });
      if (!picked) return; // 用户取消
      const project = await projectApi.register(picked);
      await openProject(project);
    } catch (err) {
      toast.error(t('sider.project.add_failed').replace('{message}', errorMessage(err)));
    }
  }, [openProject, t]);

  const handleNewChatInProject = useCallback(
    async (project: ProjectSummary) => {
      if (busyId) return;
      setBusyId(project.id);
      try {
        const { session } = await projectApi.createSession(project.id);
        await loadSessions();
        onOpenSession(session.id);
        void refresh();
        if (expandedIds.has(project.id)) void refreshSubSessions(project.id);
      } catch (err) {
        toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
      } finally {
        setBusyId(null);
      }
    },
    [busyId, expandedIds, loadSessions, onOpenSession, refresh, refreshSubSessions, t],
  );

  const handleRemoveProject = useCallback(
    async (project: ProjectSummary) => {
      try {
        await projectApi.remove(project.id);
        clearMissing(project.id);
        await refresh();
      } catch (err) {
        toast.error(t('sider.project.remove_failed').replace('{message}', errorMessage(err)));
      }
    },
    [clearMissing, refresh, t],
  );

  // P4: 子行会话删除 —— 两步确认后删除会话，联动刷新子列表/清单/会话区
  const handleDeleteSessionInProject = useCallback(
    async (project: ProjectSummary, sessionId: string) => {
      setDeletingSessionId(sessionId);
      try {
        await sessionApi.delete(sessionId);
        await loadSessions();
        await refresh();
        if (expandedIds.has(project.id)) await refreshSubSessions(project.id);
      } catch (err) {
        toast.error(
          t('sider.project.delete_session_failed').replace('{message}', errorMessage(err)),
        );
      } finally {
        setDeletingSessionId(null);
      }
    },
    [expandedIds, loadSessions, refresh, refreshSubSessions, t],
  );

  const renderSubSessions = (project: ProjectSummary) => {
    if (!expandedIds.has(project.id)) return null;
    const sessions = subSessions[project.id];
    if (loadingSubIds.has(project.id) && !sessions) {
      return (
        <div className="px-8 py-1.5 text-[10px] text-muted" data-testid="project-sessions-loading">
          {t('sider.project.sessions_loading')}
        </div>
      );
    }
    if (!sessions || sessions.length === 0) {
      return (
        <div className="px-8 py-1.5 text-[10px] text-muted" data-testid="project-sessions-empty">
          {t('sider.project.sessions_empty')}
        </div>
      );
    }
    return sessions.map((session) => (
      <div
        key={session.id}
        data-testid="project-session-row"
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
        <span className="flex-1 min-w-0 text-xs text-text-secondary truncate">
          {session.title || t('sidebar.new_chat')}
        </span>
        <span className="shrink-0 text-[10px] text-muted tabular-nums group-hover/sub:hidden">
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
    <SiderSection
      sectionKey="project"
      label={t('sider.section.project')}
      icon={Folder}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      maxHeight="30vh"
      trailing={
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
      }
      render={() => (
        <div className="flex flex-col">
          {projects.length === 0 ? (
            <div
              className="px-3 py-3 text-xs text-text-muted text-center"
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
                    onClick={() => void openProject(project)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        void openProject(project);
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
                        <span className="text-xs text-text truncate">{project.name}</span>
                        {missing && (
                          <AlertTriangle
                            className="w-3 h-3 shrink-0 text-warning"
                            aria-label={t('sider.project.missing')}
                            data-testid="project-missing-badge"
                          />
                        )}
                      </div>
                      <div className="text-[10px] text-muted truncate">{project.path}</div>
                    </div>
                    {project.sessionCount > 0 && (
                      <span
                        className="shrink-0 text-[10px] text-muted tabular-nums"
                        title={t('sider.project.session_count').replace(
                          '{count}',
                          String(project.sessionCount),
                        )}
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
                          void handleNewChatInProject(project);
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
                        onConfirm={() => void handleRemoveProject(project)}
                        className="!h-5 !w-5 !px-1 [&>svg]:!h-3 [&>svg]:!w-3"
                      />
                    </div>
                  </div>
                  {renderSubSessions(project)}
                </div>
              );
            })
          )}
        </div>
      )}
    />
  );
}

/** 子行前缀圆点：层级指示，弱于图标避免与主行混淆 */
function MessageDot() {
  return (
    <span className="w-1 h-1 rounded-full bg-current opacity-40 shrink-0" aria-hidden="true" />
  );
}

/** 移除按钮图标：与 Folder 语义呼应，弱化"删除文件"的误读 */
function FolderMinusIcon() {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
      <path d="M9 13h6" />
    </svg>
  );
}
