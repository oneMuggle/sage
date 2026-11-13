/**
 * DesignStudio — 设计工作台页面。
 *
 * 三种视图：项目列表 / 创建向导 / 生成详情（预览 + 迭代 + 导出）。
 * 数据经 `entities/design/designStore` 与设计 API 交互。
 */
import { Plus, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useDesignStore } from '../entities/design/designStore';
import { DesignCreateWizard } from '../features/design/DesignCreateWizard';
import { DesignGenerationView } from '../features/design/DesignGenerationView';
import { DesignProjectsList } from '../features/design/DesignProjectsList';
import { useI18n } from '../shared/lib/i18n';
import { PageHeader } from '../shared/ui';

export function DesignStudio() {
  const { t } = useI18n();
  const loadMeta = useDesignStore((s) => s.loadMeta);
  const loadProjects = useDesignStore((s) => s.loadProjects);

  const [creating, setCreating] = useState(false);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  const handleOpen = (projectId: string) => {
    setCreating(false);
    setActiveProjectId(projectId);
  };

  const handleBack = () => {
    setActiveProjectId(null);
    void loadProjects();
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageHeader
        title={t('design.title')}
        subtitle={t('design.subtitle')}
        actions={
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-ui-xs hover:bg-surface-hover"
              onClick={() => void loadProjects()}
            >
              <RefreshCw className="w-3 h-3" />
              {t('design.refresh')}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-ui-xs text-white"
              onClick={() => {
                setActiveProjectId(null);
                setCreating(true);
              }}
            >
              <Plus className="w-3 h-3" />
              {t('design.newProject')}
            </button>
          </div>
        }
      />

      {creating ? (
        <DesignCreateWizard
          onCancel={() => setCreating(false)}
          onCreated={(projectId) => handleOpen(projectId)}
        />
      ) : activeProjectId ? (
        <DesignGenerationView projectId={activeProjectId} onBack={handleBack} />
      ) : (
        <DesignProjectsList onOpen={handleOpen} />
      )}
    </div>
  );
}
