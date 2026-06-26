import { useMemo } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { CRON_PRESETS, validateCronExpression } from './cronValidator';

interface CronExpressionPickerProps {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}

export function CronExpressionPicker({
  value,
  onChange,
  disabled = false,
}: CronExpressionPickerProps) {
  const { t } = useI18n();
  const validation = useMemo(() => validateCronExpression(value), [value]);

  return (
    <div className="flex flex-col gap-2" data-testid="cron-picker">
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
