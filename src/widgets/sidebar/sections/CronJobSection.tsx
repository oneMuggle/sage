import { CalendarClock, Plus } from 'lucide-react';
import { useEffect } from 'react';
import { Link } from 'react-router-dom';

import { useScheduledTaskStore } from '../../../entities/scheduled/taskStore';
import { describeSchedule } from '../../../features/scheduled/cronValidator';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface CronJobSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function CronJobSection({ collapsed, onToggleCollapsed }: CronJobSectionProps) {
  const { t, locale } = useI18n();
  const tasks = useScheduledTaskStore((s) => s.tasks);
  const load = useScheduledTaskStore((s) => s.load);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SiderSection
      sectionKey="cron"
      label={t('scheduled.title')}
      icon={CalendarClock}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      trailing={
        <Link
          to="/scheduled"
          title={t('scheduled.create')}
          aria-label={t('scheduled.create')}
          className="w-5 h-5 flex items-center justify-center rounded text-muted hover:text-text hover:bg-bg-hover"
        >
          <Plus className="w-3.5 h-3.5" />
        </Link>
      }
      render={() => (
        <ul className="flex flex-col" data-testid="cron-task-list">
          {tasks.length === 0 && (
            <li className="text-[11px] text-muted px-2 py-1 italic">{t('scheduled.empty')}</li>
          )}
          {tasks.slice(0, 6).map((task) => (
            <li
              key={task.id}
              className="group flex items-center justify-between gap-2 px-2 py-1 rounded-radius-sm hover:bg-bg-hover"
            >
              <div className="flex flex-col min-w-0">
                <span className="text-xs text-text truncate">{task.name}</span>
                <span className="text-[10px] text-muted truncate">
                  {describeSchedule(task.schedule, locale as 'zh' | 'en')}
                </span>
              </div>
              <span
                className={[
                  'text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0',
                  task.enabled ? 'bg-success/10 text-success' : 'bg-muted/20 text-muted',
                ].join(' ')}
              >
                {task.enabled ? t('scheduled.status.enabled') : t('scheduled.status.disabled')}
              </span>
            </li>
          ))}
        </ul>
      )}
    />
  );
}
