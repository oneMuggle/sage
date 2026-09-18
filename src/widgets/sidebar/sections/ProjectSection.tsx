/**
 * ProjectSection — 项目模块 P1 (2026-09-13) 侧边栏入口；P2 (2026-09-13)
 * 增加行内会话子列表；P3 (2026-09-15) 增加概览面板与资料管理。
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
 * P3 概览面板：description/instructions 就地编辑保存（PATCH model_fields_set
 * 语义，未改字段保留），与后端项目元数据块联动 system prompt 注入。
 *
 * P3 资料管理：列出 status=pending_index/ready/failed 资料（status 徽标），
 * 支持用户粘贴文本新增（与 message_id 链路保存回答同入口），ready 状态
 * 自动进 system prompt；失败状态显示 error_message 提示重试，pending
 * 等待后台索引完成。
 *
 * 目录在磁盘上消失时 open 返回 410 project_path_missing：该行标记"目录
 * 不存在"，仍可点击重试或移除。数据经 projectApi（invoke → IPC → 后端
 * /api/v1/projects），刷新走 store.loadSessions() 保证会话区即时同步。
 *
 * P5 拖拽登记：把文件夹拖到本分组内容区即登记（批量、不自动打开——
 * 与 + 按钮的"登记即打开"区分，避免顺手拖拽打断当前工作流）。路径取
 * Electron `File.path`（浏览器无此属性 → 静默忽略，与 OfficeFilePicker
 * 同判据）；目录有效性由后端 validate_workspace 校验，零新增 IPC。
 * 迁移注记：Electron ≥32 需改用 webUtils.getPathForFile。
 */

import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FilePlus2,
  FileText,
  Folder,
  Plus,
  Save,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { InvokeError } from '../../../shared/api/desktopInvoke';
import {
  projectApi,
  type ProjectMaterial,
  type ProjectSummary,
} from '../../../shared/api/projectApi';
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
/** P3: 资料文本上限(对齐后端 MAX_MATERIAL_CONTENT_CHARS=1 MiB); UI 提前拦截。 */
const MATERIAL_TEXT_MAX = 1_000_000;

export function ProjectSection({
  collapsed,
  onToggleCollapsed,
  onOpenSession,
}: ProjectSectionProps) {
  const { t } = useI18n();
  const loadSessions = useStore((s) => s.loadSessions);
  const currentSessionId = useStore((s) => s.currentSessionId);
  const messages = useStore((s) => s.messages);

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
  // ===== P5: 区块局部拖拽登记 =====
  const [dropActive, setDropActive] = useState(false);
  // ===== P3: 资料 CRUD 状态 =====
  const [materials, setMaterials] = useState<Record<string, ProjectMaterial[]>>({});
  const [loadingMaterials, setLoadingMaterials] = useState<Set<string>>(new Set());
  const [addingMaterial, setAddingMaterial] = useState<Set<string>>(new Set());
  const [materialDraft, setMaterialDraft] = useState<Record<string, string>>({});
  const [removingMaterialId, setRemovingMaterialId] = useState<string | null>(null);
  const [savingAnswerProjectId, setSavingAnswerProjectId] = useState<string | null>(null);
  // ===== P3: 概览编辑 =====
  const [overviewDraft, setOverviewDraft] = useState<
    Record<string, { description: string; instructions: string; dirty: boolean }>
  >({});
  const [overviewSavingId, setOverviewSavingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await projectApi.list());
    } catch (err) {
      toast.error(t('sider.project.open_failed').replace('{message}', errorMessage(err)));
    }
  }, [t]);

  /** P5: 拖入文件夹 → 批量登记；逐条容错，成功才刷新清单。 */
  const handleDropRegister = useCallback(
    async (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDropActive(false);
      const files = Array.from(e.dataTransfer.files);
      const paths = files
        .map((f) => (f as File & { path?: string }).path)
        .filter((p): p is string => typeof p === 'string' && p.length > 0);
      if (paths.length === 0) return;
      let registered = 0;
      for (const path of paths) {
        try {
          await projectApi.register(path);
          registered += 1;
        } catch (err) {
          toast.error(t('sider.project.add_failed').replace('{message}', errorMessage(err)));
        }
      }
      if (registered > 0) {
        toast.success(t('sider.project.drop_registered').replace('{count}', String(registered)));
        await refresh();
      }
    },
    [refresh, t],
  );

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

  /** P3: 拉取项目资料。失败仅 toast。 */
  const refreshMaterials = useCallback(
    async (projectId: string) => {
      setLoadingMaterials((prev) => new Set(prev).add(projectId));
      try {
        const list = await projectApi.listMaterials(projectId);
        setMaterials((prev) => ({ ...prev, [projectId]: list }));
      } catch (err) {
        toast.error(
          t('sider.project.materials_load_failed').replace('{message}', errorMessage(err)),
        );
      } finally {
        setLoadingMaterials((prev) => {
          const next = new Set(prev);
          next.delete(projectId);
          return next;
        });
      }
    },
    [t],
  );

  /** P3: 初次展开时一次性拉资料 + 初始化概览草稿。 */
  const ensureM3Loaded = useCallback(
    async (project: ProjectSummary) => {
      const tasks: Promise<unknown>[] = [];
      if (!materials[project.id]) tasks.push(refreshMaterials(project.id));
      setOverviewDraft((prev) => {
        if (prev[project.id]) return prev;
        return {
          ...prev,
          [project.id]: {
            description: project.description ?? '',
            instructions: project.instructions ?? '',
            dirty: false,
          },
        };
      });
      await Promise.all(tasks);
    },
    [materials, refreshMaterials],
  );

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
      if (!expandedIds.has(project.id)) {
        if (!subSessions[project.id]) void refreshSubSessions(project.id);
        void ensureM3Loaded(project);
      }
    },
    [expandedIds, ensureM3Loaded, refreshSubSessions, subSessions],
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

  // ===== P3: 概览/资料 handlers =====

  const handleOverviewDraftChange = useCallback(
    (projectId: string, field: 'description' | 'instructions', value: string) => {
      setOverviewDraft((prev) => {
        const cur = prev[projectId] ?? { description: '', instructions: '', dirty: false };
        const original = projects.find((p) => p.id === projectId);
        const originalValue =
          field === 'description' ? (original?.description ?? '') : (original?.instructions ?? '');
        const next = { ...cur, [field]: value };
        return {
          ...prev,
          [projectId]: {
            ...next,
            dirty: next.description !== originalValue || next.instructions !== originalValue,
          },
        };
      });
    },
    [projects],
  );

  const handleOverviewSave = useCallback(
    async (project: ProjectSummary) => {
      const draft = overviewDraft[project.id];
      if (!draft || !draft.dirty || overviewSavingId) return;
      setOverviewSavingId(project.id);
      try {
        const updated = await projectApi.update(project.id, {
          description: draft.description,
          instructions: draft.instructions,
        });
        setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        setOverviewDraft((prev) => ({
          ...prev,
          [project.id]: {
            description: updated.description ?? '',
            instructions: updated.instructions ?? '',
            dirty: false,
          },
        }));
        toast.success(t('sider.project.overview_saved'));
      } catch (err) {
        toast.error(
          t('sider.project.overview_save_failed').replace('{message}', errorMessage(err)),
        );
      } finally {
        setOverviewSavingId(null);
      }
    },
    [overviewDraft, overviewSavingId, t],
  );

  const handleAddMaterial = useCallback(
    async (project: ProjectSummary) => {
      if (addingMaterial.has(project.id)) return;
      const text = (materialDraft[project.id] ?? '').trim();
      if (!text) return;
      if (text.length > MATERIAL_TEXT_MAX) {
        toast.error(t('sider.project.material_too_large'));
        return;
      }
      setAddingMaterial((prev) => new Set(prev).add(project.id));
      try {
        await projectApi.addMaterial(project.id, { content: text });
        setMaterialDraft((prev) => ({ ...prev, [project.id]: '' }));
        await refreshMaterials(project.id);
      } catch (err) {
        toast.error(t('sider.project.material_add_failed').replace('{message}', errorMessage(err)));
      } finally {
        setAddingMaterial((prev) => {
          const next = new Set(prev);
          next.delete(project.id);
          return next;
        });
      }
    },
    [addingMaterial, materialDraft, refreshMaterials, t],
  );

  const handleRemoveMaterial = useCallback(
    async (project: ProjectSummary, materialId: string) => {
      if (removingMaterialId) return;
      setRemovingMaterialId(materialId);
      try {
        await projectApi.removeMaterial(project.id, materialId);
        setMaterials((prev) => ({
          ...prev,
          [project.id]: (prev[project.id] ?? []).filter((m) => m.id !== materialId),
        }));
      } catch (err) {
        toast.error(
          t('sider.project.material_remove_failed').replace('{message}', errorMessage(err)),
        );
      } finally {
        setRemovingMaterialId(null);
      }
    },
    [removingMaterialId, t],
  );

  /**
   * P3: 把当前 active 会话中"最近一条 assistant 消息"保存为项目资料。
   * 前提: 当前会话 id 与项目的"绑定会话"一致 —— 后端按 session→workspace
   * 绑定反向校验; 不一致时返回 403, UI 给"消息不属于该项目"提示。
   */
  const handleSaveAnswerAsMaterial = useCallback(
    async (project: ProjectSummary) => {
      if (savingAnswerProjectId) return;
      if (!currentSessionId) {
        toast.error(t('sider.project.save_answer_no_session'));
        return;
      }
      const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
      if (!lastAssistant) {
        toast.error(t('sider.project.save_answer_no_assistant'));
        return;
      }
      setSavingAnswerProjectId(project.id);
      try {
        await projectApi.saveAnswerAsMaterial(project.id, lastAssistant.id);
        await refreshMaterials(project.id);
        toast.success(t('sider.project.save_answer_ok'));
      } catch (err) {
        const code = (err as InvokeError)?.status_code;
        if (code === 403) {
          toast.error(t('sider.project.save_answer_mismatch'));
        } else if (code === 404) {
          toast.error(t('sider.project.save_answer_not_found'));
        } else {
          toast.error(
            t('sider.project.save_answer_failed').replace('{message}', errorMessage(err)),
          );
        }
      } finally {
        setSavingAnswerProjectId(null);
      }
    },
    [currentSessionId, messages, refreshMaterials, savingAnswerProjectId, t],
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

  /** P3 渲染: 概览面板 (description + instructions 编辑) */
  const renderOverviewPanel = (project: ProjectSummary) => {
    if (!expandedIds.has(project.id)) return null;
    const draft = overviewDraft[project.id];
    const saving = overviewSavingId === project.id;
    return (
      <div
        className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
        data-testid="project-overview-panel"
      >
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-muted uppercase tracking-wide">
            {t('sider.project.overview_title')}
          </span>
          <button
            type="button"
            data-testid="project-overview-save"
            disabled={!draft?.dirty || saving}
            onClick={() => void handleOverviewSave(project)}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Save className="w-3 h-3" aria-hidden="true" />
            {saving ? t('sider.project.overview_saving') : t('sider.project.overview_save')}
          </button>
        </div>
        <label className="block text-[10px] text-muted mb-0.5">
          {t('sider.project.overview_description')}
        </label>
        <textarea
          data-testid="project-overview-description"
          value={draft?.description ?? ''}
          onChange={(e) => handleOverviewDraftChange(project.id, 'description', e.target.value)}
          rows={2}
          className="w-full text-[11px] px-1.5 py-1 rounded border border-border bg-bg resize-y"
          placeholder={t('sider.project.overview_description_placeholder')}
        />
        <label className="block text-[10px] text-muted mb-0.5 mt-1.5">
          {t('sider.project.overview_instructions')}
        </label>
        <textarea
          data-testid="project-overview-instructions"
          value={draft?.instructions ?? ''}
          onChange={(e) => handleOverviewDraftChange(project.id, 'instructions', e.target.value)}
          rows={3}
          className="w-full text-[11px] px-1.5 py-1 rounded border border-border bg-bg resize-y"
          placeholder={t('sider.project.overview_instructions_placeholder')}
        />
      </div>
    );
  };

  /** P3 渲染: 资料管理面板 */
  const renderMaterialsPanel = (project: ProjectSummary) => {
    if (!expandedIds.has(project.id)) return null;
    const list = materials[project.id];
    const isLoading = loadingMaterials.has(project.id) && !list;
    const isAdding = addingMaterial.has(project.id);
    const draftText = materialDraft[project.id] ?? '';
    return (
      <div
        className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
        data-testid="project-materials-panel"
      >
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-muted uppercase tracking-wide">
            {t('sider.project.materials_title')}
          </span>
          <button
            type="button"
            data-testid="project-save-answer"
            disabled={savingAnswerProjectId === project.id || !currentSessionId}
            onClick={() => void handleSaveAnswerAsMaterial(project)}
            title={
              currentSessionId
                ? t('sider.project.save_answer_title')
                : t('sider.project.save_answer_no_session')
            }
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <FilePlus2 className="w-3 h-3" aria-hidden="true" />
            {t('sider.project.save_answer')}
          </button>
        </div>

        {isLoading ? (
          <div className="text-[10px] text-muted py-1" data-testid="project-materials-loading">
            {t('sider.project.materials_loading')}
          </div>
        ) : list && list.length > 0 ? (
          <ul className="space-y-1" data-testid="project-material-list">
            {list.map((m) => (
              <li
                key={m.id}
                data-testid="project-material-row"
                data-status={m.status}
                className="flex items-start gap-1.5 px-1.5 py-1 rounded bg-bg/60 border border-border/30"
              >
                <FileText className="w-3 h-3 mt-0.5 shrink-0 text-muted" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <MaterialStatusBadge status={m.status} />
                    <span className="text-muted truncate">
                      {m.sourceMessageId
                        ? t('sider.project.material_from_message').replace(
                            '{id}',
                            m.sourceMessageId,
                          )
                        : t('sider.project.material_direct')}
                    </span>
                    <span className="text-muted/60 tabular-nums ml-auto">
                      {formatRelativeTime(m.createdAt)}
                    </span>
                  </div>
                  {m.status === 'failed' && m.errorMessage && (
                    <div
                      className="text-[10px] text-warning mt-0.5 truncate"
                      title={m.errorMessage}
                      data-testid="project-material-error"
                    >
                      {m.errorMessage}
                    </div>
                  )}
                  {m.status === 'ready' && m.content && (
                    <div className="text-[10px] text-text-secondary mt-0.5 line-clamp-2">
                      {m.content.slice(0, 120)}
                      {m.content.length > 120 ? '…' : ''}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  data-testid="project-material-remove"
                  aria-label={t('sider.project.material_remove')}
                  disabled={removingMaterialId === m.id}
                  onClick={() => void handleRemoveMaterial(project, m.id)}
                  className="shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-muted hover:text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 className="w-3 h-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-[10px] text-muted py-1" data-testid="project-materials-empty">
            {t('sider.project.materials_empty')}
          </div>
        )}

        <div className="mt-2 space-y-1">
          <textarea
            data-testid="project-material-input"
            value={draftText}
            onChange={(e) =>
              setMaterialDraft((prev) => ({ ...prev, [project.id]: e.target.value }))
            }
            rows={3}
            placeholder={t('sider.project.material_input_placeholder')}
            className="w-full text-[11px] px-1.5 py-1 rounded border border-border bg-bg resize-y"
          />
          <div className="flex justify-end">
            <button
              type="button"
              data-testid="project-material-add"
              disabled={isAdding || !draftText.trim()}
              onClick={() => void handleAddMaterial(project)}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Plus className="w-3 h-3" aria-hidden="true" />
              {t('sider.project.material_add')}
            </button>
          </div>
        </div>
      </div>
    );
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
              className="px-3 py-2 text-xs text-primary text-center"
              data-testid="project-drop-hint"
            >
              {t('sider.project.drop_hint')}
            </div>
          )}
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
                  {renderOverviewPanel(project)}
                  {renderMaterialsPanel(project)}
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

/** P3: 资料状态徽标——颜色映射 ready/pending/failed, 标签本地化 */
function MaterialStatusBadge({ status }: { status: ProjectMaterial['status'] }) {
  const { t } = useI18n();
  const palette = {
    ready: 'bg-success/15 text-success border-success/30',
    pending_index: 'bg-muted/20 text-muted border-muted/30',
    failed: 'bg-warning/15 text-warning border-warning/30',
  } as const;
  const labelKey = {
    ready: 'sider.project.material_status_ready',
    pending_index: 'sider.project.material_status_pending',
    failed: 'sider.project.material_status_failed',
  } as const;
  return (
    <span
      data-testid={`project-material-status-${status}`}
      className={`shrink-0 px-1 py-px rounded border text-[9px] ${palette[status]}`}
    >
      {t(labelKey[status])}
    </span>
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
