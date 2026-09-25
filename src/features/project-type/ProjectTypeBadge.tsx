/**
 * 项目类型徽章 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.2
 * 在侧边栏项目列表中显示项目类型标识
 */

import { clsx } from 'clsx';
import { Code, BookOpen, Briefcase, User, HelpCircle } from 'lucide-react';

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
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  },
  research: {
    label: '科研',
    icon: <BookOpen className="h-3 w-3" />,
    color: 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
  },
  business: {
    label: '事务',
    icon: <Briefcase className="h-3 w-3" />,
    color: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  },
  personal: {
    label: '个人',
    icon: <User className="h-3 w-3" />,
    color: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
  },
};

export function ProjectTypeBadge({ type, detected, className }: ProjectTypeBadgeProps) {
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
      </span>
    );
  }

  const config = TYPE_CONFIG[type];

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium',
        config.color,
        detected && 'ring-1 ring-blue-400 ring-offset-1 dark:ring-offset-gray-900',
        className,
      )}
      title={detected ? '自动检测的项目类型' : '手动设置的项目类型'}
    >
      {config.icon}
      {config.label}
    </span>
  );
}
