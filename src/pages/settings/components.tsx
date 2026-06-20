/**
 * Settings 页面 - 共用组件和类型
 */

import type { useSettings } from '../../features/manage-settings/useSettings';

// ==================== 共用类型 ====================

export interface EndpointsTabProps {
  settings: ReturnType<typeof useSettings>['settings'];
  updateSettings: ReturnType<typeof useSettings>['updateSettings'];
}

export interface SettingRowProps {
  label: string;
  desc: string;
  children: React.ReactNode;
}

export interface ToggleProps {
  value: boolean;
  onChange: (v: boolean) => void;
}

// ==================== 共用组件 ====================

export function SettingRow({ label, desc, children }: SettingRowProps) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border">
      <div>
        <div className="text-sm text-text">{label}</div>
        <div className="text-xs text-muted mt-0.5">{desc}</div>
      </div>
      <div>{children}</div>
    </div>
  );
}

export function Toggle({ value, onChange }: ToggleProps) {
  return (
    <button
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
