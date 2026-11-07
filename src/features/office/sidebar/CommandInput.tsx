import { useState } from 'react';

import { useI18n } from '../../../shared/lib/i18n';

export interface CommandInputProps {
  disabled: boolean;
  pending: boolean;
  onSubmit: (value: string) => void;
}

export function CommandInput({ disabled, pending, onSubmit }: CommandInputProps): JSX.Element {
  const { t } = useI18n();
  const [value, setValue] = useState('');

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || pending) return;
    onSubmit(trimmed);
    setValue('');
  };

  return (
    <div className="flex items-end gap-2 border-t border-border p-2">
      <textarea
        data-testid="office-ai-command-input"
        aria-label={t('office.ai.sidebar.placeholder')}
        rows={2}
        value={value}
        disabled={disabled}
        placeholder={t('office.ai.sidebar.placeholder')}
        className="flex-1 resize-none rounded border border-border bg-surface px-2 py-1 text-sm"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' || event.shiftKey) return;
          event.preventDefault();
          submit();
        }}
      />
      <button
        type="button"
        data-testid="office-ai-command-send"
        disabled={disabled || pending || !value.trim()}
        className="rounded bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-40"
        onClick={submit}
      >
        {pending ? t('office.ai.sidebar.thinking') : t('office.ai.sidebar.send')}
      </button>
    </div>
  );
}
