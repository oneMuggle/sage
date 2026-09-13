/**
 * ProjectBadge — 项目模块 P3 (2026-09-13)：Chat 头部当前项目标识。
 *
 * 对标 Cursor 标题栏 workspace 名 / Claude Code 会话头仓库名：会话绑定
 * 了工作区时，在对话头部显示"在哪个项目里"，消除多项目并行时的上下文
 * 迷失。展示组件刻意不依赖 SessionWorkspaceProvider —— workspacePath
 * 由调用方（Chat.tsx 已有的 useCurrentWorkspace()）透传，便于测试。
 *
 * 名称解析：优先精确匹配已登记项目（projectApi.list() 按 path 相等）；
 * 未登记的历史绑定回退路径 basename；清单拉取失败同样静默降级，永不
 * 因徽标阻塞对话功能。
 */

import { Folder } from 'lucide-react';
import { useEffect, useState } from 'react';

import { projectApi, type ProjectSummary } from '../../shared/api/projectApi';

interface ProjectBadgeProps {
  workspacePath: string | undefined | null;
}

function basenameOf(path: string): string {
  const normalized = path.replace(/[\\/]+$/, '');
  const last = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
  return last === -1 ? normalized : normalized.slice(last + 1);
}

export function ProjectBadge({ workspacePath }: ProjectBadgeProps) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);

  useEffect(() => {
    if (!workspacePath) return;
    let cancelled = false;
    projectApi
      .list()
      .then((result) => {
        if (!cancelled) setProjects(result);
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

  return (
    <span
      data-testid="chat-project-badge"
      title={workspacePath}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-hover border border-border text-xs text-text-secondary max-w-[220px] shrink-0"
    >
      <Folder className="w-3 h-3 shrink-0 text-muted" aria-hidden="true" />
      <span className="truncate">{name}</span>
    </span>
  );
}
