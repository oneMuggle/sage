/**
 * 2026-11 信息架构整理：页头「环境」按钮 + 浮层。
 *
 * 把原 Office 页顶部常驻的 `OfficeCapabilityBar`（本机能力探测）和
 * `OfficeStagingInspector`（暂存只读诊断）收进 Radix Popover，避免低频
 * 的诊断组件占据首屏空间。
 *
 * 关键点：
 * - `forceMount` + `data-[state=closed]:hidden`：Popper/Content 在关闭
 *   时也保留在 DOM 但 `display:none`，`OfficeCapabilityBar` 得以保持
 *   mounted，确保 `onCapabilities` 在打开浮层前就能拿到探测结果
 *   （`pdfAvailableForDocument` 依赖此 prop 控制预览工具栏的
 *   高保真开关）。
 * - `OfficeStagingInspector` 延迟挂载：首次打开才渲染，避免在页面加载
 *   时就跑后端暂存诊断请求。
 * - `data-testid`：`office-env-button`（触发）、`office-env-popover`（浮层），
 *   便于测试用 `waitFor` 探测浮层展开。
 */

import * as Popover from '@radix-ui/react-popover';
import { Cpu } from 'lucide-react';
import { useState } from 'react';

import { OfficeCapabilityBar } from '../../features/office/OfficeCapabilityBar';
import { OfficeStagingInspector } from '../../features/office/OfficeStagingInspector';
import type { OfficeCapabilities } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface OfficeEnvironmentButtonProps {
  workspacePath: string | null;
  onCapabilities: (caps: OfficeCapabilities | null) => void;
}

export function OfficeEnvironmentButton({
  workspacePath,
  onCapabilities,
}: OfficeEnvironmentButtonProps) {
  const { t } = useI18n();
  // Inspector 挂载一次后保持 — 关闭/重开浮层不会再次触发后端诊断。
  const [inspectorMounted, setInspectorMounted] = useState(false);

  return (
    <Popover.Root
      onOpenChange={(open) => {
        if (open) setInspectorMounted(true);
      }}
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          data-testid="office-env-button"
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-sm border border-border text-text-secondary hover:bg-bg-hover"
        >
          <Cpu className="w-4 h-4" />
          {t('office.env.title')}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          forceMount
          align="end"
          sideOffset={6}
          data-testid="office-env-popover"
          className="z-50 w-96 max-h-[70vh] overflow-y-auto rounded-radius-md border border-border bg-surface shadow-xl p-4 space-y-4 data-[state=closed]:hidden"
        >
          <section>
            <h3 className="text-xs font-medium text-text-secondary mb-2">
              {t('office.env.capabilities')}
            </h3>
            <OfficeCapabilityBar onCapabilities={onCapabilities} />
          </section>
          {workspacePath && (
            <section>
              <h3 className="text-xs font-medium text-text-secondary mb-2">
                {t('office.env.staging')}
              </h3>
              {inspectorMounted && (
                <OfficeStagingInspector key={workspacePath} workspacePath={workspacePath} />
              )}
            </section>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
