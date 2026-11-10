// src/features/task-center/TaskCenterPanel.tsx
//
// 任务列表内容。compact = 侧边栏分区（每组最多 3 条），full = /tasks 页面。
import { useMemo, useState } from 'react';

import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { TaskCenterCard } from './TaskCenterCard';
import type { UnifiedTaskEntry, UnifiedTaskSource } from './unifiedTaskModel';
import { useTaskCenterActions } from './useTaskCenterActions';
import { useUnifiedTasks } from './useUnifiedTasks';

const GROUP_ORDER = ['active', 'failed', 'finished'] as const;
type GroupKey = (typeof GROUP_ORDER)[number];

const COMPACT_LIMIT = 3;

export interface TaskCenterPanelProps {
  variant: 'compact' | 'full';
}

export function TaskCenterPanel({ variant }: TaskCenterPanelProps) {
  const { t } = useI18n();
  const actions = useTaskCenterActions();
  const { groups, all, loading, error } = useUnifiedTasks();
  const [sourceFilter, setSourceFilter] = useState<UnifiedTaskSource | 'all'>('all');

  const visibleGroups = useMemo(() => {
    const byGroup = variant === 'compact' ? (['active', 'failed'] as const) : GROUP_ORDER;
    return byGroup
      .map((key) => {
        let list: UnifiedTaskEntry[] = groups[key as GroupKey];
        if (sourceFilter !== 'all') list = list.filter((e) => e.source === sourceFilter);
        return { key: key as GroupKey, list };
      })
      .filter((g) => g.list.length > 0);
  }, [groups, sourceFilter, variant]);

  const sources = useMemo(() => {
    const set = new Set<UnifiedTaskSource>();
    for (const e of all) set.add(e.source);
    return [...set];
  }, [all]);

  if (error && all.length === 0) {
    return <div className="px-3 py-2 text-ui-2xs text-error">{error}</div>;
  }

  if (all.length === 0 && !loading) {
    return (
      <div className="px-3 py-2 text-ui-2xs text-muted">
        {variant === 'compact' ? t('taskCenter.section.empty') : t('taskCenter.page.empty')}
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {variant === 'full' && (
        <div className="px-3 pb-2 flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setSourceFilter('all')}
            className={sourceFilter === 'all' ? 'text-primary' : 'text-muted'}
          >
            {t('taskCenter.filter.all')}
          </button>
          {sources.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSourceFilter(s)}
              className={sourceFilter === s ? 'text-primary' : 'text-muted'}
            >
              {t(`taskCenter.source.${s}` as TranslationKey)}
            </button>
          ))}
        </div>
      )}

      {visibleGroups.map(({ key, list }) => {
        const shown = variant === 'compact' ? list.slice(0, COMPACT_LIMIT) : list;
        const overflow = list.length - shown.length;
        return (
          <div key={key} className="mt-1">
            <div className="px-3 py-1 text-ui-2xs uppercase text-muted">
              {t(`taskCenter.group.${key}` as TranslationKey)}
            </div>
            {shown.map((entry) => (
              <TaskCenterCard
                key={entry.id}
                entry={entry}
                actions={actions}
                compact={variant === 'compact'}
              />
            ))}
            {overflow > 0 && (
              <div className="px-3 py-1 text-ui-2xs text-muted">
                {t('taskCenter.section.more').replace('{count}', String(overflow))}
              </div>
            )}
          </div>
        );
      })}

      {variant === 'full' && groups.finished.length > 0 && (
        <div className="px-3 pt-2">
          <button
            type="button"
            onClick={actions.clearFinished}
            className="text-ui-2xs text-muted hover:text-text"
          >
            {t('taskCenter.action.clearFinished')}
          </button>
        </div>
      )}
    </div>
  );
}
