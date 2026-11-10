/**
 * 2026-11 信息架构整理：LaTeX 子 tab 容器。
 *
 * 把原先平铺在 Office 页的 7 个 LaTeX 面板（import / template / audit /
 * pdf-audit / compliance / profile-library / build）按用户任务分组为
 * 3 个子 tab：项目与编译 / 模板与规范 / 审校与合规。
 *
 * 使用 Radix forceMount + hidden 让切换过的面板保持 mounted，保留本地
 * 状态（上传历史、选中规范等），避免回到 LaTeX 分区就丢状态。父层
 * (Office.tsx) 负责解析 URL 的 `latex` 参数，本组件通过 `active/onChange`
 * 受控呈现。
 */

import type { ReactNode } from 'react';

import { LatexAuditPanel } from '../../features/office/LatexAuditPanel';
import { LatexBuildPanel } from '../../features/office/LatexBuildPanel';
import { LatexCompliancePanel } from '../../features/office/LatexCompliancePanel';
import { LatexPdfAuditPanel } from '../../features/office/LatexPdfAuditPanel';
import { LatexProfileLibraryPanel } from '../../features/office/LatexProfileLibraryPanel';
import { LatexProjectImportPanel } from '../../features/office/LatexProjectImportPanel';
import { LatexTemplatePanel } from '../../features/office/LatexTemplatePanel';
import { useKeepAliveTabs } from '../../shared/lib/hooks/useKeepAliveTabs';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../shared/ui/Tabs';

import { OFFICE_LATEX_TAB_IDS, parseOfficeLatexTab, type OfficeLatexTabId } from './officeTabs';

export interface OfficeLatexTabProps {
  active: OfficeLatexTabId;
  onChange: (next: OfficeLatexTabId) => void;
}

const LATEX_TAB_LABEL_KEYS: Record<OfficeLatexTabId, TranslationKey> = {
  project: 'office.latex.project',
  templates: 'office.latex.templates',
  audit: 'office.latex.audit',
};

function renderLatexSection(id: OfficeLatexTabId): ReactNode {
  switch (id) {
    case 'project':
      return (
        <div className="space-y-4">
          <LatexProjectImportPanel />
          <LatexBuildPanel />
        </div>
      );
    case 'templates':
      return (
        <div className="space-y-4">
          <LatexTemplatePanel />
          <LatexProfileLibraryPanel />
        </div>
      );
    case 'audit':
      return (
        <div className="space-y-4">
          <LatexAuditPanel />
          <LatexPdfAuditPanel />
          <LatexCompliancePanel />
        </div>
      );
  }
}

export function OfficeLatexTab({ active, onChange }: OfficeLatexTabProps) {
  const { t } = useI18n();
  const mounted = useKeepAliveTabs(active);

  return (
    <div className="space-y-4">
      <Tabs value={active} onValueChange={(value) => onChange(parseOfficeLatexTab(value))}>
        <TabsList aria-label={t('office.latex.tabs.label')} data-testid="office-latex-tabs">
          {OFFICE_LATEX_TAB_IDS.map((id) => (
            <TabsTrigger key={id} value={id} data-testid={`office-latex-tab-${id}`}>
              {t(LATEX_TAB_LABEL_KEYS[id])}
            </TabsTrigger>
          ))}
        </TabsList>
        {OFFICE_LATEX_TAB_IDS.map((id) => (
          <TabsContent
            key={id}
            value={id}
            forceMount
            hidden={active !== id}
            data-testid={`office-latex-panel-${id}`}
          >
            {mounted.includes(id) && renderLatexSection(id)}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
