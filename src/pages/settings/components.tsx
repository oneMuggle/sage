/**
 * Settings 页面 - 共用组件和类型
 */

import { useState } from 'react';

import { APPLY_MODE_LABELS, type ApplyMode } from '../../entities/setting/metadata';
import type { useSettings } from '../../features/manage-settings/useSettings';

// ==================== 共用类型 ====================

export interface EndpointsTabProps {
  settings: ReturnType<typeof useSettings>['settings'];
  updateSettings: ReturnType<typeof useSettings>['updateSettings'];
}

export interface SettingRowProps {
  label: string;
  desc?: string;
  children: React.ReactNode;
}

export interface ToggleProps {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  // RD16 (round26): 可选测试锚点 —— 设置页测试用 getByTestId 定位开关。
  testId?: string;
}

// ==================== 共用组件 ====================

export function SettingRow({ label, desc, children }: SettingRowProps) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border">
      <div>
        <div className="text-sm text-text">{label}</div>
        {desc ? <div className="text-xs text-muted mt-0.5">{desc}</div> : null}
      </div>
      <div>{children}</div>
    </div>
  );
}

export function Toggle({ value, onChange, disabled = false, testId }: ToggleProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      data-testid={testId}
      className={`w-9 h-5 rounded-full relative transition-colors ${
        value ? 'bg-primary' : 'bg-border'
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
  const label = APPLY_MODE_LABELS[mode];
  return (
    <span
      data-testid={`setting-apply-mode-${mode}`}
      title={label.en}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${
        mode === 'restart'
          ? 'bg-error/10 text-error'
          : mode === 'immediate'
            ? 'bg-success/10 text-success'
            : mode === 'save-only'
              ? 'bg-bg-muted text-muted'
              : 'bg-primary/10 text-primary'
      }`}
    >
      {compact ? label.zh : `保存后：${label.zh}`}
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
          {open ? '收起' : '展开'}
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
