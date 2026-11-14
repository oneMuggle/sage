/**
 * DesignProjectsList — 设计项目卡片网格。
 *
 * 数据来自 `entities/design/designStore`；点击卡片进入生成视图。
 */
import { FileStack, LayoutTemplate, Loader2, Trash2 } from 'lucide-react';
import { useEffect } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { DesignProject } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

interface DesignProjectsListProps {
  onOpen: (projectId: string) => void;
}

function statusClass(status: DesignProject['status']): string {
  switch (status) {
    case 'complete':
      return 'bg-emerald-500/10 text-emerald-600';
    case 'generating':
      return 'bg-amber-500/10 text-amber-600';
    case 'error':
      return 'bg-red-500/10 text-red-600';
    default:
      return 'bg-surface-hover text-text-secondary';
  }
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function DesignProjectsList({ onOpen }: DesignProjectsListProps) {
  const { t } = useI18n();
  const projects = useDesignStore((s) => s.projects);
  const loading = useDesignStore((s) => s.loadingProjects);
  const error = useDesignStore((s) => s.errorProjects);
  const loadProjects = useDesignStore((s) => s.loadProjects);
  const deleteProject = useDesignStore((s) => s.deleteProject);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  if (loading && projects.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-ui-sm text-text-secondary">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        {t('design.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-ui-sm">
        <p className="text-red-500">{error}</p>
        <button
          type="button"
          className="px-3 py-1.5 rounded-md border border-border hover:bg-surface-hover"
          onClick={() => void loadProjects()}
        >
          {t('design.retry')}
        </button>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-6">
        <LayoutTemplate className="w-8 h-8 text-text-tertiary" />
        <p className="text-ui-md font-medium text-text">{t('design.empty.title')}</p>
        <p className="text-ui-sm text-text-secondary max-w-md">{t('design.empty.hint')}</p>
      </div>
    );
  }

  const handleDelete = (project: DesignProject) => {
    if (!window.confirm(t('design.deleteConfirm'))) return;
    void deleteProject(project.id);
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4">
      <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {projects.map((project) => (
          <li key={project.id}>
            <div
              role="button"
              tabIndex={0}
              data-testid={`design-project-${project.id}`}
              onClick={() => onOpen(project.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') onOpen(project.id);
              }}
              className="group h-full rounded-lg border border-border bg-surface p-4 text-left hover:border-accent/50 hover:bg-surface-hover transition-colors cursor-pointer"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-ui-md font-medium text-text truncate">{project.name}</p>
                  <p className="mt-0.5 text-ui-xs text-text-secondary">
                    {t(`design.kind.${project.kind}`)}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-ui-xs ${statusClass(project.status)}`}
                >
                  {t(`design.status.${project.status}`)}
                </span>
              </div>
              <p className="mt-3 line-clamp-2 text-ui-sm text-text-secondary min-h-[2.5rem]">
                {project.brief}
              </p>
              <div className="mt-3 flex items-center justify-between text-ui-xs text-text-tertiary">
                <span>
                  {t('design.project.updatedAt').replace('{time}', formatTime(project.updated_at))}
                </span>
                <button
                  type="button"
                  aria-label={t('design.delete')}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/10 hover:text-red-600 transition"
                  onClick={(event) => {
                    event.stopPropagation();
                    handleDelete(project);
                  }}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center gap-1.5 text-ui-xs text-text-tertiary">
        <FileStack className="w-3.5 h-3.5" />
        {projects.length}
      </div>
    </div>
  );
}
