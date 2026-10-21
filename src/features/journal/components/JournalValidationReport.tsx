import type { JournalViolation } from '../../../shared/api/types';

const SEVERITY_STYLE: Record<JournalViolation['severity'], string> = {
  error: 'border-red-300 bg-red-50 text-red-800',
  warning: 'border-amber-300 bg-amber-50 text-amber-800',
  info: 'border-slate-300 bg-slate-50 text-slate-700',
};

const SEVERITY_LABEL: Record<JournalViolation['severity'], string> = {
  error: '错误',
  warning: '警告',
  info: '提示',
};

export interface JournalValidationReportProps {
  violations: JournalViolation[];
  errorCount: number;
  warningCount: number;
}

export function formatJournalValidationMarkdown(
  violations: JournalViolation[],
  errorCount: number,
  warningCount: number,
): string {
  const lines = [
    '# 期刊排版校验报告 (Journal Validation Report)',
    '',
    `- **错误数**: ${errorCount}`,
    `- **警告数**: ${warningCount}`,
    `- **总计条目**: ${violations.length}`,
  ];
  if (violations.length === 0) {
    lines.push('', '_无违规项_');
  } else {
    lines.push('', '## 违规详情');
    for (const v of violations) {
      const sug = v.suggestion ? ` — 建议: ${v.suggestion}` : '';
      lines.push(
        `- **[${SEVERITY_LABEL[v.severity]}] ${v.rule_id}** (${v.location}): ${v.message}${sug}`,
      );
    }
  }
  return lines.join('\n');
}

export function formatJournalValidationJson(
  violations: JournalViolation[],
  errorCount: number,
  warningCount: number,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      errorCount,
      warningCount,
      total: violations.length,
      violations,
    },
    null,
    2,
  );
}

export function JournalValidationReport({
  violations,
  errorCount,
  warningCount,
}: JournalValidationReportProps) {
  if (violations.length === 0) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
        无违规项
      </div>
    );
  }

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div
      className="space-y-2 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm"
      data-testid="journal-validation-report"
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">
          {errorCount} 错误 · {warningCount} 警告
        </span>
        <div className="flex items-center gap-1"></div>
      </div>
      <ul className="space-y-1">
        {violations.map((v, idx) => (
          <li
            key={`${v.rule_id}-${idx}`}
            className={`rounded border px-2 py-1 text-xs ${SEVERITY_STYLE[v.severity]}`}
          >
            <div className="font-medium">
              [{SEVERITY_LABEL[v.severity]}] {v.rule_id} · {v.location}
            </div>
            <div>{v.message}</div>
            {v.suggestion && <div className="mt-1 italic text-slate-600">建议: {v.suggestion}</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}
