// src/widgets/sidebar/sections/TaskCenterSection.tsx
//
// 内容列「任务」分区。轮询不在本组件内（折叠即不渲染），
// 统一由常驻的 TaskCenterRuntimeHost 承担（spec §5.4）。
import { ListChecks } from 'lucide-react';

import { TaskCenterPanel } from '../../../features/task-center/TaskCenterPanel';
import { useUnifiedTasks } from '../../../features/task-center/useUnifiedTasks';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

export interface TaskCenterSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function TaskCenterSection({ collapsed, onToggleCollapsed }: TaskCenterSectionProps) {
  const { t } = useI18n();
  const { attentionCount } = useUnifiedTasks();

  return (
    <SiderSection
      sectionKey="tasks"
      label={t('taskCenter.section.title')}
      icon={ListChecks}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      maxHeight="320px"
      trailing={
        attentionCount > 0 ? (
          <span className="text-ui-2xs text-muted">{attentionCount}</span>
        ) : undefined
      }
      render={() => <TaskCenterPanel variant="compact" />}
    />
  );
}
