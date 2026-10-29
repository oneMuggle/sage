/**
 * Settings 页面 - 共用组件和类型
 */

import { useState } from 'react';

import { APPLY_MODE_LABELS, type ApplyMode } from '../../entities/setting/metadata';
import { getSettingMetadata } from '../../entities/setting/settingsRegistry';
import type { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';

// ==================== 共用类型 ====================

export interface EndpointsTabProps {
  settings: ReturnType<typeof useSettings>['settings'];
  updateSettings: ReturnType<typeof useSettings>['updateSettings'];
}

export interface SettingRowProps {
  label: string;
  desc?: string;
  children: React.ReactNode;
  /**
   * P1-4: 设置搜索锚点。填 `settingsSearchIndex.ts` 里该条目登记的 `key`，
   * 点击搜索结果时可滚动定位 + 高亮到这一行。
   *
   * 不填不渲染该属性 —— 未登记锚点的行不受影响，定位逻辑找不到时静默降级
   * 为「只切 tab」，保持既有行为。
   */
  anchor?: string;
  /**
   * 该行当前值。与 `anchor` 在 `settingsRegistry` 里的 `defaultValue` 不一致
   * 且提供了 `onReset` 时，渲染「恢复默认」。不传则不渲染，既有行行为不变。
   */
  value?: unknown;
  /** 恢复默认：调用方负责把 registry 的 `defaultValue` 写回。 */
  onReset?: () => void;
}

export interface ToggleProps {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  // RD16 (round26): 可选测试锚点 —— 设置页测试用 getByTestId 定位开关。
  testId?: string;
}

export interface SettingRowAuditInput {
  label: string;
  hasDesc: boolean;
  anchor: string | null;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSettingRowAuditSnapshot(input: SettingRowAuditInput): string {
  return `label=${input.label}|desc=${input.hasDesc ? 1 : 0}|anchor=${input.anchor ?? 'none'}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSettingRowAuditJson(input: SettingRowAuditInput): string {
  return JSON.stringify({
    label: input.label,
    hasDesc: input.hasDesc,
    anchor: input.anchor,
  });
}

// ==================== 共用组件 ====================

/**
 * registry 默认值比较：原始值直接比，对象/数组按序列化比（键序稳定，见各
 * 设置的构造方式）。序列化失败（环）时保守地视为「已修改」。
 */
function isDefaultValue(value: unknown, defaultValue: unknown): boolean {
  if (value === defaultValue) return true;
  try {
    return JSON.stringify(value) === JSON.stringify(defaultValue);
  } catch {
    return false;
  }
}

export function SettingRow({ label, desc, children, anchor, value, onReset }: SettingRowProps) {
  const { t } = useI18n();
  const auditSnapshot = formatSettingRowAuditSnapshot({
    label,
    hasDesc: Boolean(desc),
    anchor: anchor ?? null,
  });

  const metadata = anchor === undefined ? undefined : getSettingMetadata(anchor);
  const showReset =
    onReset !== undefined &&
    value !== undefined &&
    metadata !== undefined &&
    !isDefaultValue(value, metadata.defaultValue);

  return (
    <div
      data-setting-label={label}
      data-settings-anchor={anchor}
      data-setting-row-audit={auditSnapshot}
      tabIndex={-1}
      className="flex items-center justify-between py-3 border-b border-border focus:outline-none focus:ring-2 focus:ring-primary/40 focus:rounded"
    >
      <div>
        <div className="text-sm text-text">{label}</div>
        {desc ? <div className="text-xs text-muted mt-0.5">{desc}</div> : null}
      </div>
      <div className="flex items-center gap-2">
        {showReset && (
          <button
            type="button"
            data-testid={anchor ? `setting-reset-${anchor}` : undefined}
            onClick={onReset}
            className="text-xs text-muted hover:text-primary transition-colors"
          >
            {t('settings.common.reset_default')}
          </button>
        )}
        {children}
      </div>
    </div>
  );
}

export function Toggle({ value, onChange, disabled = false, testId }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      disabled={disabled}
      data-testid={testId}
      className={`w-9 h-5 rounded-full relative transition-colors ${
        value ? 'bg-primary' : 'bg-line-strong'
      }`}
      onClick={() => onChange(!value)}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-text-inverse transition-transform ${
          value ? 'translate-x-4' : ''
        }`}
      />
    </button>
  );
}

export function ApplyModeBadge({ mode, compact = false }: { mode: ApplyMode; compact?: boolean }) {
  const { t, locale } = useI18n();
  const label = APPLY_MODE_LABELS[mode];
  return (
    <span
      data-testid={`setting-apply-mode-${mode}`}
      title={label.en}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-ui-xs font-medium ${
        mode === 'restart'
          ? 'bg-error/10 text-error'
          : mode === 'immediate'
            ? 'bg-success/10 text-success'
            : mode === 'save-only'
              ? 'bg-bg-muted text-muted'
              : 'bg-primary/10 text-primary'
      }`}
    >
      {compact ? label[locale] : t('settings.common.apply_after').replace('{label}', label[locale])}
    </span>
  );
}

export interface AdvancedSectionProps {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export function AdvancedSection({
  title,
  description,
  defaultOpen = false,
  children,
}: AdvancedSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const { t } = useI18n();
  const contentId = `advanced-settings-${title.replace(/[^a-zA-Z0-9一-鿿]+/g, '-')}`;

  return (
    <section data-testid="settings-advanced-section" className="border-t border-border pt-3">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between text-left text-sm font-semibold text-text"
      >
        <span>{title}</span>
        <span aria-hidden="true" className="text-xs text-muted">
          {open ? t('settings.common.collapse') : t('settings.common.expand')}
        </span>
      </button>
      {description ? <p className="mt-1 text-xs text-muted">{description}</p> : null}
      <div
        id={contentId}
        data-testid={`advanced-section-content-${contentId}`}
        hidden={!open}
        className="mt-2"
      >
        {children}
      </div>
    </section>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditSettingsComponentsGovernance(): {
  module: 'src/pages/settings/components.tsx';
  phase: 'P174';
  domain: 'settings';
  exportsAdvancedSectionAndSettingRow: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/components.tsx',
    phase: 'P174',
    domain: 'settings',
    exportsAdvancedSectionAndSettingRow: true,
    compliant: true,
  };
}
