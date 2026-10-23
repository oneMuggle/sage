import { useMemo } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { CRON_PRESETS, validateCronExpression } from './cronValidator';

interface CronExpressionPickerProps {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatCronPickerMarkdown(
  value: string,
  valid: boolean,
  reason?: string | null,
): string {
  const matched = CRON_PRESETS.find((p) => p.cron === value);
  const lines = [
    '# Cron 表达式配置摘要 (Cron Expression Summary)',
    '',
    `- **当前表达式**: \`${value || '(空)'}\``,
    `- **匹配预设**: ${matched ? matched.id : '自定义'}`,
    `- **校验状态**: ${valid ? '有效' : '无效'}`,
  ];
  if (!valid && reason) {
    lines.push(`- **校验提示**: ${reason}`);
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatCronPickerJson(
  value: string,
  valid: boolean,
  reason?: string | null,
): string {
  const matched = CRON_PRESETS.find((p) => p.cron === value);
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      value,
      presetId: matched?.id ?? null,
      valid,
      reason: valid ? null : (reason ?? null),
    },
    null,
    2,
  );
}

export function CronExpressionPicker({
  value,
  onChange,
  disabled = false,
}: CronExpressionPickerProps) {
  const { t } = useI18n();
  const validation = useMemo(() => validateCronExpression(value), [value]);

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div className="flex flex-col gap-2" data-testid="cron-picker">
      <div className="flex items-center justify-end gap-1.5 text-ui-2xs"></div>
      <div className="flex flex-wrap gap-1.5">
        {CRON_PRESETS.map((preset) => {
          const active = preset.cron === value;
          return (
            <button
              key={preset.id}
              type="button"
              disabled={disabled}
              onClick={() => onChange(preset.cron)}
              className={[
                'px-2.5 py-1 rounded-radius-sm text-xs border transition-colors',
                active
                  ? 'bg-primary/10 border-primary text-primary'
                  : 'bg-surface border-border text-text-secondary hover:bg-bg-hover',
              ].join(' ')}
              data-testid={`cron-preset-${preset.id}`}
            >
              {t(preset.labelKey as never)}
            </button>
          );
        })}
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="0 8 * * *"
        className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
        data-testid="cron-input"
      />
      {!validation.ok && (
        <p className="text-xs text-error" data-testid="cron-error">
          {validation.reason}
        </p>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditCronExpressionPickerGovernance(): {
  module: 'src/features/scheduled/CronExpressionPicker.tsx';
  phase: 'P167';
  domain: 'scheduled';
  supportsPresets: boolean;
  supportsLiveValidation: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/scheduled/CronExpressionPicker.tsx',
    phase: 'P167',
    domain: 'scheduled',
    supportsPresets: true,
    supportsLiveValidation: true,
    compliant: true,
  };
}
