/**
 * ProjectSection — 项目模块 P1 (2026-09-13) 侧边栏入口。
 *
 * 对标主流 AI 工具的"最近项目"概念（Cursor Recent Workspaces / Claude Code
 * 项目 → 会话归属）：列出用户登记的工作目录，点击即进入该项目 —— 后端
 * 复用项目最近的活跃会话（无则新建并绑定项目目录），前端切换过去。
 *
 * 行内操作（hover 显现）：
 *  - +：在该项目下显式新建一个绑定会话；
 *  - TwoStepDelete：从清单移除（只删注册行，不动磁盘与任何会话）。
 *
 * 目录在磁盘上消失时 open 返回 410 project_path_missing：该行标记"目录
 * 不存在"，仍可点击重试或移除。数据经 projectApi（invoke → IPC → 后端
 * /api/v1/projects），刷新走 store.loadSessions() 保证会话区即时同步。
 */

import { AlertTriangle, Folder, Plus } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import type { InvokeError } from '../../../shared/api/desktopInvoke';
import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
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
    [busyId, clearMissing, loadSessions, onOpenSession, refresh, t],
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
      } catch (err) {
        toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
      } finally {
        setBusyId(null);
      }
    },
    [busyId, loadSessions, onOpenSession, refresh, t],
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
              return (
                <div
                  key={project.id}
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
                  className="group flex items-center gap-2 mx-1.5 px-2 py-1.5 rounded cursor-pointer hover:bg-bg-hover"
                  title={`${project.name}\n${project.path}`}
                >
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
              );
            })
          )}
        </div>
      )}
    />
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
