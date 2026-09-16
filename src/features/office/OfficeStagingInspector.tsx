import { useEffect, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type { OfficeStagingReport } from '../../shared/types/electron-api';

/** User-triggered, read-only evidence. No collector/deletion action is exposed. */
export function OfficeStagingInspector({ workspacePath }: { workspacePath: string }) {
  const { t } = useI18n();
  const generation = useRef(0);
  const [report, setReport] = useState<OfficeStagingReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    generation.current += 1;
    setReport(null);
    setError(null);
    setBusy(false);
    return () => {
      generation.current += 1;
    };
  }, [workspacePath]);

  const inspect = async () => {
    const current = ++generation.current;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const preview = window.electronAPI?.office?.previewStaging;
      if (!preview) throw new Error(t('office.staging.unavailable'));
      const result = await preview(workspacePath);
      if (current === generation.current) setReport(result);
    } catch (e) {
      if (current === generation.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  };

  return (
    <section className="rounded border border-border p-3 text-sm">
      <button
        type="button"
        disabled={busy}
        onClick={() => void inspect()}
        className="rounded border border-border px-3 py-1 disabled:opacity-50"
      >
        {t('office.staging.inspect')}
      </button>
      <p className="mt-2 text-muted">{t('office.staging.notice')}</p>
      {error && <p role="alert">{error}</p>}
      {report && (
        <div aria-live="polite">
          {report.truncated && <p>{t('office.staging.truncated')}</p>}
          {report.items.length === 0 && <p>{t('office.staging.empty')}</p>}
          <ul className="mt-2 max-h-64 overflow-auto">
            {report.items.map((item) => (
              <li key={`${item.docType}/${item.documentId}`}>
                <code>
                  {item.docType}/{item.documentId}
                </code>
                {' — '}
                {t(`office.staging.${item.status}`)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
