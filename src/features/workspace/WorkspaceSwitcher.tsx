/**
 * WorkspaceSwitcher — 工作区切换器 (2026-10-29, P2)。
 *
 * 取代旧的 `ProjectBadge`：徽标只回答"名字叫什么"，而用户真正要回答的是
 * 三个问题——当前在哪个目录、这个目录是谁决定的、它还能不能用。本组件把
 * 三件事收进一个 chip + 下拉浮层：
 *
 *   1. **来源标签**：项目 / 会话绑定 / 用户偏好 / 自动检测 / 草稿，
 *      取自后端决策链 `backend/services/default_workspace.py` 的 `source`，
 *      前端不自行推导。
 *   2. **健康状态**：后端 `GET /workspace/health` 的只读探测结果，用圆点
 *      区分正常 / 只读 / 已丢失，避免工具调用时才炸出看不懂的报错。
 *   3. **切换入口**：列出已登记项目，写入用户偏好并重绑当前会话。
 *
 * 全链路 fail-open：任何一次探测失败都只降级展示，不阻塞头部渲染。
 */

import * as Popover from '@radix-ui/react-popover';
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Folder,
  Loader2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { projectApi, type ProjectSummary } from '../../shared/api/projectApi';
import { workspaceApi, type WorkspaceHealthStatus } from '../../shared/api/workspaceApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';
import { clientLogger } from '../../shared/log/client';
import { getArchetypeBlueprint } from '../project-type/archetypeBlueprints';

export interface WorkspaceSwitcherProps {
  /** 当前会话生效的工作区目录；为空表示尚未绑定。 */
  workspacePath?: string | null;
  /** 当前会话 id —— 有值时切换会重绑该会话。 */
  sessionId?: string | null;
  /** 打开项目工作台。 */
  onOpenWorkbench?: () => void;
}

/** 后端 `WorkspaceSource` 枚举 → i18n 词条。 */
const SOURCE_LABEL_KEYS: Record<string, TranslationKey> = {
  project: 'workspace.switcher.source.project',
  session_binding: 'workspace.switcher.source.sessionBinding',
  user_preference: 'workspace.switcher.source.userPreference',
  detected: 'workspace.switcher.source.detected',
  scratch: 'workspace.switcher.source.scratch',
};

/** 后端 `WorkspaceHealth` 枚举 → i18n 词条。 */
const HEALTH_LABEL_KEYS: Record<string, TranslationKey> = {
  healthy: 'workspace.switcher.health.healthy',
  read_only: 'workspace.switcher.health.readOnly',
  missing: 'workspace.switcher.health.missing',
  not_a_directory: 'workspace.switcher.health.notADirectory',
  inaccessible: 'workspace.switcher.health.inaccessible',
};

/** 健康状态圆点配色。 */
const HEALTH_DOT_CLASS: Record<string, string> = {
  healthy: 'bg-emerald-500',
  read_only: 'bg-amber-500',
  missing: 'bg-red-500',
  not_a_directory: 'bg-red-500',
  inaccessible: 'bg-red-500',
};

const VCS_SHORT_LABELS: Record<string, string> = {
  git: 'Git',
  builtin: '快照',
};

function basenameOf(path: string): string {
  const normalized = path.replace(/[\\/]+$/, '');
  const last = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
  return last === -1 ? normalized : normalized.slice(last + 1);
}

/** 宽松比较两个路径是否指向同一目录（忽略尾部分隔符与大小写）。 */
function samePath(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false;
  const norm = (p: string) => p.replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
}

export function WorkspaceSwitcher({
  workspacePath,
  sessionId,
  onOpenWorkbench,
}: WorkspaceSwitcherProps) {
  const { t } = useI18n();
  const ctx = useOptionalWorkspaceContext();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [defaultPath, setDefaultPath] = useState<string | null>(null);
  const [defaultSource, setDefaultSource] = useState<string | null>(null);
  const [health, setHealth] = useState<WorkspaceHealthStatus | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);
  const [busy, setBusy] = useState(false);
  // "已复制"状态 1.8s 后自动收回；定时器挂 ref 以便卸载时清理，
  // 避免在已卸载组件上 setState。
  const copyResetRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
        copyResetRef.current = null;
      }
    },
    [],
  );

  // 默认工作区的来源由后端决策链给出；前端只读取，不推导。
  useEffect(() => {
    let cancelled = false;
    workspaceApi
      .getDefault({ sessionId: sessionId ?? undefined })
      .then((resolution) => {
        if (cancelled) return;
        setDefaultPath(resolution.path);
        setDefaultSource(resolution.source);
      })
      .catch(() => {
        if (!cancelled) setDefaultSource(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 健康探测：只读，失败即视为未知（灰点），不阻塞渲染。
  useEffect(() => {
    if (!workspacePath) {
      setHealth(null);
      return;
    }
    let cancelled = false;
    workspaceApi
      .getHealth(workspacePath)
      .then((status) => {
        if (!cancelled) setHealth(status);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  useEffect(() => {
    if (!workspacePath || typeof projectApi?.list !== 'function') return;
    let cancelled = false;
    projectApi
      .list()
      .then((result) => {
        if (!cancelled && Array.isArray(result)) setProjects(result);
      })
      .catch(() => {
        if (!cancelled) setProjects(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  /** 当前目录的来源：与默认解析一致时用默认来源，否则是会话绑定。 */
  const currentSource = useMemo(() => {
    if (!workspacePath) return null;
    if (samePath(defaultPath, workspacePath)) return defaultSource;
    return 'session_binding';
  }, [workspacePath, defaultPath, defaultSource]);

  const registered = useMemo(
    () => (projects ?? []).find((p) => samePath(p.path, workspacePath)) ?? null,
    [projects, workspacePath],
  );

  const name = registered?.name ?? (workspacePath ? basenameOf(workspacePath) : '');
  const effectiveType = registered?.projectType ?? registered?.detectedType ?? null;
  const blueprint = effectiveType ? getArchetypeBlueprint(effectiveType) : null;
  const stageLabel =
    blueprint && registered?.projectStage
      ? (blueprint.stages.find((s) => s.id === registered.projectStage)?.label ??
        registered.projectStage)
      : null;
  const vcsBadgeLabel = registered?.vcsMode ? VCS_SHORT_LABELS[registered.vcsMode] : null;

  const sourceLabel = currentSource
    ? t(SOURCE_LABEL_KEYS[currentSource] ?? 'workspace.switcher.source.detected')
    : null;
  const healthKey = health?.health ?? null;
  const healthLabel = healthKey
    ? t(HEALTH_LABEL_KEYS[healthKey] ?? 'workspace.switcher.health.unknown')
    : null;
  const dotClass = healthKey
    ? (HEALTH_DOT_CLASS[healthKey] ?? 'bg-text-tertiary')
    : 'bg-text-tertiary';
  const isScratch = currentSource === 'scratch';

  const handleCopyWorkspacePath = useCallback(async () => {
    if (!workspacePath) return;
    if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current);
    setCopiedPath(true);
    copyResetRef.current = window.setTimeout(() => {
      copyResetRef.current = null;
      setCopiedPath(false);
    }, 1800);
    try {
      await navigator.clipboard?.writeText(workspacePath);
    } catch {
      // 剪贴板不可用（离线 / 测试环境）→ 已置的"已复制"图标会被超时收回
    }
  }, [workspacePath]);

  const handleSelectProject = useCallback(
    async (project: ProjectSummary) => {
      if (busy) return;
      setBusy(true);
      try {
        if (sessionId) {
          await workspaceApi.bind(sessionId, project.path);
        }
        // 记住默认目录是次要动作：失败不回滚已完成的切换。
        try {
          await workspaceApi.setPreference(project.path);
        } catch (error) {
          clientLogger.warn('workspace switcher: 写入默认工作区偏好失败', {
            error: error instanceof Error ? error.message : String(error),
          });
        }
        await ctx?.refresh();
        setOpen(false);
        toast.success(t('workspace.switcher.switched'));
      } catch (error) {
        toast.error(error instanceof Error ? error.message : t('workspace.switcher.failed'));
      } finally {
        setBusy(false);
      }
    },
    [busy, sessionId, ctx, t],
  );

  if (!workspacePath) return null;

  return (
    <span className="inline-flex items-center gap-1 shrink-0">
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            type="button"
            data-testid="workspace-switcher-trigger"
            title={workspacePath}
            className="inline-flex items-center gap-1 max-w-[280px] shrink-0 rounded-full border border-border bg-bg-hover px-2 py-0.5 text-xs text-text-secondary hover:bg-surface"
          >
            <span
              data-testid="workspace-switcher-health-dot"
              aria-hidden="true"
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`}
            />
            <Folder className="w-3 h-3 shrink-0 text-muted" aria-hidden="true" />
            <span className="truncate">{name}</span>
            {blueprint && (
              <span
                data-testid="workspace-switcher-type-badge"
                className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-ui-2xs font-medium text-primary"
              >
                {blueprint.label}
              </span>
            )}
            {stageLabel && (
              <span
                data-testid="workspace-switcher-stage-badge"
                className="shrink-0 rounded bg-surface px-1 py-0.5 text-ui-2xs text-text-tertiary border border-border/60"
              >
                {stageLabel}
              </span>
            )}
            {vcsBadgeLabel && (
              <span
                data-testid="workspace-switcher-vcs-badge"
                className="shrink-0 rounded bg-emerald-500/10 px-1 py-0.5 text-ui-2xs font-medium text-emerald-600"
              >
                {vcsBadgeLabel}
              </span>
            )}
            {sourceLabel && (
              <span
                data-testid="workspace-switcher-source-badge"
                className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-ui-2xs font-medium text-primary"
              >
                {sourceLabel}
              </span>
            )}
            <ChevronDown className="w-3 h-3 shrink-0 opacity-60" aria-hidden="true" />
          </button>
        </Popover.Trigger>

        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={6}
            className="z-50 w-96 max-h-[70vh] overflow-y-auto rounded-radius-md border border-border bg-surface shadow-xl"
          >
            <div className="border-b border-border px-3 py-2">
              <div className="truncate text-xs text-text" title={workspacePath}>
                {workspacePath}
              </div>
              <div className="mt-1 flex items-center gap-2 text-ui-xs text-text-tertiary">
                <span
                  data-testid="workspace-switcher-health-dot-detail"
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`}
                />
                <span data-testid="workspace-switcher-health-label">{healthLabel}</span>
                {health?.detail && <span className="truncate">· {health.detail}</span>}
              </div>
              {isScratch && (
                <div
                  data-testid="workspace-switcher-scratch-hint"
                  className="mt-2 rounded bg-amber-500/10 px-2 py-1 text-ui-xs text-amber-700 dark:text-amber-400"
                >
                  {t('workspace.switcher.scratchHint')}
                </div>
              )}
            </div>

            <div className="px-3 pt-2 pb-1 text-ui-xs uppercase tracking-wide text-text-tertiary">
              {t('workspace.switcher.switchTo')}
            </div>

            {busy && (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-text-secondary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('workspace.switcher.switching')}
              </div>
            )}

            {!busy && (projects?.length ?? 0) === 0 && (
              <div className="px-3 py-2 text-xs text-text-tertiary">
                {t('workspace.switcher.noProjects')}
              </div>
            )}

            {!busy &&
              (projects ?? []).map((project) => (
                <button
                  key={project.id}
                  type="button"
                  data-testid="workspace-switcher-option"
                  disabled={busy}
                  onClick={() => void handleSelectProject(project)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-bg-hover disabled:opacity-50"
                >
                  <Folder
                    className="h-3.5 w-3.5 shrink-0 text-text-secondary"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-text">{project.name}</span>
                    <span className="block truncate text-ui-xs text-text-tertiary">{project.path}</span>
                  </span>
                  {samePath(project.path, workspacePath) && (
                    <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                  )}
                </button>
              ))}

            {health && !health.isUsable && (
              <div className="mt-1 border-t border-border px-3 py-2">
                <span
                  data-testid="workspace-switcher-unusable-warning"
                  className="inline-flex items-center gap-1 text-ui-2xs text-red-600 dark:text-red-400"
                >
                  <AlertTriangle className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
                  {t('workspace.switcher.unusable')}
                </span>
              </div>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      <button
        type="button"
        onClick={() => void handleCopyWorkspacePath()}
        data-testid="workspace-switcher-copy-path-btn"
        aria-label={t('workspace.switcher.copyPath')}
        title={`${t('workspace.switcher.copyPath')} (${workspacePath})`}
        className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
      >
        {copiedPath ? (
          <Check className="w-2.5 h-2.5 shrink-0 text-emerald-600" aria-hidden="true" />
        ) : (
          <Copy className="w-2.5 h-2.5 shrink-0" aria-hidden="true" />
        )}
      </button>
      {onOpenWorkbench && (
        <button
          type="button"
          onClick={onOpenWorkbench}
          data-testid="workspace-switcher-workbench-btn"
          aria-label={t('workspace.switcher.workbench')}
          title={`${t('workspace.switcher.workbench')} (/projects)`}
          className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <ExternalLink className="w-2.5 h-2.5 shrink-0" aria-hidden="true" />
          <span className="hidden xl:inline">{t('workspace.switcher.workbench')}</span>
        </button>
      )}
    </span>
  );
}
