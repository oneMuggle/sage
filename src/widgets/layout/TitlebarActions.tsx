import { ArrowLeft, ArrowRight } from 'lucide-react';
import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import { useNavigationHistory } from '../../shared/lib/useNavigationHistory';

export function formatTitlebarActionsAuditSnapshot(opts: {
  canBack?: boolean;
  canForward?: boolean;
}): string {
  return `titlebarActions|back=${opts.canBack ? 1 : 0}|forward=${opts.canForward ? 1 : 0}`;
}

export function formatTitlebarActionsAuditJson(opts: {
  canBack?: boolean;
  canForward?: boolean;
}): string {
  return JSON.stringify({
    canBack: Boolean(opts.canBack),
    canForward: Boolean(opts.canForward),
  });
}

/**
 * Title bar back/forward navigation buttons.
 * Reads from NavHistoryProvider context (returns no-op if not in provider).
 * Buttons are disabled when canBack/canForward are false.
 */
export function TitlebarActions() {
  const { t } = useI18n();
  const history = useNavigationHistory();
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const canBack = history?.canBack ?? false;
  const canForward = history?.canForward ?? false;

  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatTitlebarActionsAuditSnapshot({ canBack, canForward }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatTitlebarActionsAuditJson({ canBack, canForward }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

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
      <span
        data-testid="titlebar-actions-copy-snapshot"
        onClick={() => void handleCopySnapshot()}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="titlebar-actions-copy-json"
        onClick={() => void handleCopyJson()}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </div>
  );
}
