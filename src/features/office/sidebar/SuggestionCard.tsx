import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';

export interface SuggestionCardProps {
  messageId: string;
  suggestion: SuggestionCardData;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  /** Defaults to `office-ai-suggestion`. */
  testIdPrefix?: string;
  /** When true, both action buttons render with `disabled`. */
  disabled?: boolean;
}

export function SuggestionCard({
  messageId,
  suggestion,
  onApply,
  onSkip,
  testIdPrefix = 'office-ai-suggestion',
  disabled = false,
}: SuggestionCardProps): JSX.Element {
  const { t } = useI18n();

  const statusLabel =
    suggestion.applied === 'applied'
      ? t('office.ai.audit.applied')
      : suggestion.applied === 'skipped'
        ? t('office.ai.audit.skipped')
        : null;

  return (
    <div
      data-testid={`${testIdPrefix}-${suggestion.id}`}
      className="mt-2 rounded border border-border bg-bg-subtle p-2 text-xs"
    >
      <div className="mb-1 font-medium text-text-secondary">
        {fillTemplate(t('office.ai.audit.paragraph'), {
          index: String(suggestion.paraIndex + 1),
        })}
      </div>
      <del className="mb-1 block text-text-muted">{suggestion.originalText}</del>
      <ins className="mb-2 block text-text no-underline">{suggestion.suggestedText}</ins>
      {statusLabel ? (
        <span className="text-text-muted">{statusLabel}</span>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            data-testid={`${testIdPrefix}-apply-${suggestion.id}`}
            disabled={disabled}
            className="rounded bg-accent px-2 py-0.5 text-accent-foreground disabled:opacity-40"
            onClick={() => onApply(messageId, suggestion)}
          >
            {t('office.ai.sidebar.apply')}
          </button>
          <button
            type="button"
            data-testid={`${testIdPrefix}-skip-${suggestion.id}`}
            disabled={disabled}
            className="rounded px-2 py-0.5 text-text-muted hover:bg-surface-hover disabled:opacity-40"
            onClick={() => onSkip(messageId, suggestion.id)}
          >
            {t('office.ai.audit.skip')}
          </button>
        </div>
      )}
    </div>
  );
}
