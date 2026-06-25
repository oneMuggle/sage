import { Clock } from 'lucide-react';

import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface CronJobSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function CronJobSection({ collapsed, onToggleCollapsed }: CronJobSectionProps) {
  const { t } = useI18n();
  return (
    <SiderSection
      sectionKey="cron"
      label={t('sider.section.cron')}
      icon={Clock}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      render={() => (
        <div className="px-3 py-2 text-xs text-muted">占位 - 定时任务将在 Phase 8 实现</div>
      )}
    />
  );
}
