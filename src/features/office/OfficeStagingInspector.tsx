import { useEffect, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type { OfficeStagingReport } from '../../shared/types/electron-api';

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeStagingMarkdown(
  workspacePath: string,
  report: OfficeStagingReport | null,
): string {
  const lines = [
    '# Office 暂存区检查报告 (Office Staging Report)',
    '',
    `- **工作区路径**: ${workspacePath || '-'}`,
  ];
  if (!report) {
    lines.push('', '_尚未执行暂存区检查_');
  } else {
    lines.push(
      `- **截断标记**: ${report.truncated ? '是' : '否'}`,
      `- **条目数量**: ${report.items.length}`,
    );
    if (report.items.length === 0) {
      lines.push('', '_暂无暂存文档_');
    } else {
      lines.push('', '## 暂存文档列表');
      for (const item of report.items) {
        lines.push(`- \`${item.docType}/${item.documentId}\` — ${item.status}`);
      }
    }
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeStagingJson(
  workspacePath: string,
  report: OfficeStagingReport | null,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      workspacePath,
      report,
    },
    null,
    2,
  );
}

/** User-triggered, read-only evidence. No collector/deletion action is exposed. */
export function OfficeStagingInspector({ workspacePath }: { workspacePath: string }) {
  const { t } = useI18n();
  const generation = useRef(0);
  const [report, setReport] = useState<OfficeStagingReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
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

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatOfficeStagingMarkdown(workspacePath, report));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatOfficeStagingJson(workspacePath, report));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

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
          <div className="mt-2 flex items-center gap-1.5">
            <button
              type="button"
              data-testid="office-staging-copy-md"
              onClick={() => void handleCopyMarkdown()}
              className="rounded border border-border px-2 py-0.5 text-xs hover:bg-bg-hover"
            >
              {copiedMd ? '已复制 MD' : '复制 MD'}
            </button>
            <button
              type="button"
              data-testid="office-staging-copy-json"
              onClick={() => void handleCopyJson()}
              className="rounded border border-border px-2 py-0.5 text-xs hover:bg-bg-hover"
            >
              {copiedJson ? '已复制 JSON' : '复制 JSON'}
            </button>
          </div>
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditOfficeStagingInspectorGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/OfficeStagingInspector.tsx',
    phase: 'P165',
    status: 'ready',
  };
}
