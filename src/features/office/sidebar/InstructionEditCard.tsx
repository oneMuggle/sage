import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { useI18n } from '../../../shared/lib/i18n';

import { SuggestionCard } from './SuggestionCard';

export interface InstructionEditCardProps {
  messageId: string;
  suggestions: SuggestionCardData[];
  busy: boolean;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  /** When provided and `pendingCount > 1`, renders the apply-all button. */
  onApplyAll?: (messageId: string) => void;
  /** Defaults to `office-ai-instruction-edit`. */
  testIdPrefix?: string;
}

export function InstructionEditCard({
  messageId,
  suggestions,
  busy,
  onApply,
  onSkip,
  onApplyAll,
  testIdPrefix = 'office-ai-instruction-edit',
}: InstructionEditCardProps): JSX.Element {
  const { t } = useI18n();

  const pendingCount = suggestions.filter((suggestion) => suggestion.applied === 'pending').length;

  return (
    <div data-testid={testIdPrefix}>
      {suggestions.map((suggestion) => (
        <SuggestionCard
          key={suggestion.id}
          messageId={messageId}
          suggestion={suggestion}
          onApply={onApply}
          onSkip={onSkip}
          testIdPrefix={testIdPrefix}
          disabled={busy}
        />
      ))}
      {onApplyAll && pendingCount > 1 ? (
        <button
          type="button"
          data-testid="office-ai-audit-apply-all"
          disabled={busy}
          className="mt-2 w-full rounded bg-accent px-2 py-1 text-xs text-accent-foreground disabled:opacity-40"
          onClick={() => onApplyAll(messageId)}
        >
          {t('office.ai.audit.apply_all')}
        </button>
      ) : null}
    </div>
  );
}
