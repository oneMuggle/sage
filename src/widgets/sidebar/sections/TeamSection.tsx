import { Users } from 'lucide-react';

import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface TeamSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function TeamSection({ collapsed, onToggleCollapsed }: TeamSectionProps) {
  const { t } = useI18n();
  return (
    <SiderSection
      sectionKey="team"
      label={t('sider.section.team')}
      icon={Users}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      render={() => (
        <div className="px-3 py-2 text-xs text-muted">占位 - 团队协作将在 Phase 6 接入</div>
      )}
    />
  );
}
