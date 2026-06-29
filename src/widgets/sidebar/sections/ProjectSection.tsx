import { Folder } from 'lucide-react';

import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface ProjectSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function ProjectSection({ collapsed, onToggleCollapsed }: ProjectSectionProps) {
  const { t } = useI18n();
  return (
    <SiderSection
      sectionKey="project"
      label={t('sider.section.project')}
      icon={Folder}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      render={() => (
        <div className="px-3 py-2 text-xs text-muted">占位 - 项目列表将在 Phase 4 接入</div>
      )}
    />
  );
}
