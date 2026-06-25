import { ArrowLeft, ArrowRight } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';
import { useNavigationHistory } from '../../shared/lib/useNavigationHistory';

/**
 * Title bar back/forward navigation buttons.
 * Reads from NavHistoryProvider context (returns no-op if not in provider).
 * Buttons are disabled when canBack/canForward are false.
 */
export function TitlebarActions() {
  const { t } = useI18n();
  const history = useNavigationHistory();

  const canBack = history?.canBack ?? false;
  const canForward = history?.canForward ?? false;

  return (
    <div className="no-drag flex items-center gap-1">
      <button
        type="button"
        aria-label={t('nav.back')}
        disabled={!canBack}
        onClick={() => history?.back()}
        className="p-1.5 rounded hover:bg-bg-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
      </button>
      <button
        type="button"
        aria-label={t('nav.forward')}
        disabled={!canForward}
        onClick={() => history?.forward()}
        className="p-1.5 rounded hover:bg-bg-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );
}
