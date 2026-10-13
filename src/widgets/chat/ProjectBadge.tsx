/**
 * ProjectBadge — 项目模块 P3 (2026-09-13) + Phase P22 多态语境增强 + Phase P28 版本保护徽标与路径复制：Chat 头部当前项目标识。
 *
 * 对标 Cursor 标题栏 workspace 名 / Claude Code 会话头仓库名：会话绑定
 * 了工作区时，在对话头部显示"在哪个项目里"，同时展示项目形态（代码工程/一般档案/科学研究/个人空间）、
 * 当前生命周期阶段徽章、版本保护模式，并提供一键复制工作区路径与打开项目工作台的快捷入口。
 */

import { Check, Copy, ExternalLink, Folder } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getArchetypeBlueprint } from '../../features/project-type/archetypeBlueprints';
import { projectApi, type ProjectSummary } from '../../shared/api/projectApi';

interface ProjectBadgeProps {
  workspacePath: string | undefined | null;
  onOpenWorkbench?: () => void;
}

function basenameOf(path: string): string {
  const normalized = path.replace(/[\\/]+$/, '');
  const last = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
  return last === -1 ? normalized : normalized.slice(last + 1);
}

const VCS_SHORT_LABELS: Record<string, string> = {
  git: 'Git',
  builtin: '快照',
};

export function ProjectBadge({ workspacePath, onOpenWorkbench }: ProjectBadgeProps) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);

  useEffect(() => {
    if (!workspacePath || typeof projectApi?.list !== 'function') return;
    let cancelled = false;
    projectApi
      .list()
      .then((result) => {
        if (!cancelled && Array.isArray(result)) setProjects(result);
      })
      .catch(() => {
        // 清单不可用（后端离线等）→ 降级为 basename 展示
        if (!cancelled) setProjects(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  if (!workspacePath) return null;

  const registered = projects?.find((p) => p.path === workspacePath);
  const name = registered?.name ?? basenameOf(workspacePath);
  const effectiveType = registered?.projectType ?? registered?.detectedType ?? null;
  const blueprint = effectiveType ? getArchetypeBlueprint(effectiveType) : null;
  const stageLabel =
    blueprint && registered?.projectStage
      ? (blueprint.stages.find((s) => s.id === registered.projectStage)?.label ??
        registered.projectStage)
      : null;
  const vcsBadgeLabel = registered?.vcsMode ? VCS_SHORT_LABELS[registered.vcsMode] : null;

  const handleCopyWorkspacePath = async () => {
    try {
      await navigator.clipboard?.writeText(workspacePath);
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <span className="inline-flex items-center gap-1 shrink-0">
      <span
        data-testid="chat-project-badge"
        title={workspacePath}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-hover border border-border text-xs text-text-secondary max-w-[280px] shrink-0"
      >
        <Folder className="w-3 h-3 shrink-0 text-muted" aria-hidden="true" />
        <span className="truncate">{name}</span>
        {blueprint && (
          <span
            data-testid="chat-project-type-badge"
            className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-ui-2xs font-medium text-primary"
          >
            {blueprint.label}
          </span>
        )}
        {stageLabel && (
          <span
            data-testid="chat-project-stage-badge"
            className="shrink-0 rounded bg-surface px-1 py-0.5 text-ui-2xs text-text-tertiary border border-border/60"
          >
            {stageLabel}
          </span>
        )}
        {vcsBadgeLabel && (
          <span
            data-testid="chat-project-vcs-badge"
            className="shrink-0 rounded bg-emerald-500/10 px-1 py-0.5 text-ui-2xs font-medium text-emerald-600"
          >
            {vcsBadgeLabel}
          </span>
        )}
      </span>
      <button
        type="button"
        onClick={() => void handleCopyWorkspacePath()}
        data-testid="chat-project-copy-path-btn"
        aria-label="复制项目路径"
        title={`复制项目路径 (${workspacePath})`}
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
          data-testid="chat-project-workbench-btn"
          aria-label="打开项目工作台"
          title="打开项目工作台 (/projects)"
          className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <ExternalLink className="w-2.5 h-2.5 shrink-0" aria-hidden="true" />
          <span className="hidden xl:inline">工作台</span>
        </button>
      )}
    </span>
  );
}
