// src/pages/TasksPage.tsx
//
// /tasks 路由薄壳。⚠️ 不要加进 src/pages/index.ts barrel ——
// pagesIndex.p142.test.ts 硬断言 exportedPageCount === 5。
import { TaskCenterPanel } from '../features/task-center/TaskCenterPanel';
import { useI18n } from '../shared/lib/i18n';

export function TasksPage() {
  const { t } = useI18n();
  return (
    <div className="h-full flex flex-col">
      <header className="px-6 py-4 border-b border-ui-border">
        <h1 className="text-lg font-medium text-text">{t('taskCenter.page.title')}</h1>
        <p className="mt-1 text-ui-sm text-muted">{t('taskCenter.page.subtitle')}</p>
      </header>
      <div className="flex-1 overflow-y-auto py-2">
        <TaskCenterPanel variant="full" />
      </div>
    </div>
  );
}
