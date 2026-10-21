/**
 * 项目类型徽章 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.2
 * 在侧边栏项目列表中显示项目类型标识
 */

import { clsx } from 'clsx';
import { Code, BookOpen, Briefcase, User, HelpCircle } from 'lucide-react';
import { useState } from 'react';

import type { ProjectType } from '../../shared/api';

export interface ProjectTypeBadgeProps {
  type: ProjectType | null | undefined;
  detected?: boolean;
  className?: string;
}

const TYPE_CONFIG: Record<ProjectType, { label: string; icon: React.ReactNode; color: string }> = {
  coding: {
    label: '编码',
    icon: <Code className="h-3 w-3" />,
    color: 'bg-role-blue text-role-blue-text',
  },
  research: {
    label: '科研',
    icon: <BookOpen className="h-3 w-3" />,
    color: 'bg-role-purple text-role-purple-text',
  },
  business: {
    label: '事务',
    icon: <Briefcase className="h-3 w-3" />,
    color: 'bg-role-green text-role-green-text',
  },
  personal: {
    label: '个人',
    icon: <User className="h-3 w-3" />,
    color: 'bg-role-orange text-role-orange-text',
  },
};

export function formatProjectTypeBadgeAuditSnapshot(opts: {
  type?: ProjectType | null;
  detected?: boolean;
}): string {
  return `projectTypeBadge|type=${opts.type || 'unclassified'}|detected=${opts.detected ? 1 : 0}`;
}

export function formatProjectTypeBadgeAuditJson(opts: {
  type?: ProjectType | null;
  detected?: boolean;
}): string {
  return JSON.stringify({
    type: opts.type || 'unclassified',
    detected: Boolean(opts.detected),
  });
}

export function ProjectTypeBadge({ type, detected, className }: ProjectTypeBadgeProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  /* v8 ignore start */
  const handleCopySnapshot = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatProjectTypeBadgeAuditSnapshot({ type, detected }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(formatProjectTypeBadgeAuditJson({ type, detected }));
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */
  if (!type) {
    return (
      <span
        className={clsx(
          'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium',
          'bg-muted text-muted-foreground',
          className,
        )}
      >
        <HelpCircle className="h-3 w-3" />
        未分类
        <span
          data-testid="project-type-badge-copy-snapshot"
          onClick={(e) => void handleCopySnapshot(e)}
        >
          {copiedSnapshot ? '已复制快照' : ''}
        </span>
        <span
          data-testid="project-type-badge-copy-json"
          onClick={(e) => void handleCopyJson(e)}
        >
          {copiedJson ? '已复制JSON' : ''}
        </span>
      </span>
    );
  }

  const config = TYPE_CONFIG[type];

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium',
        config.color,
        detected && 'ring-1 ring-info ring-offset-1 ring-offset-surface',
        className,
      )}
      title={detected ? '自动检测的项目类型' : '手动设置的项目类型'}
    >
      {config.icon}
      {config.label}
      <span
        data-testid="project-type-badge-copy-snapshot"
        onClick={(e) => void handleCopySnapshot(e)}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="project-type-badge-copy-json"
        onClick={(e) => void handleCopyJson(e)}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </span>
  );
}
