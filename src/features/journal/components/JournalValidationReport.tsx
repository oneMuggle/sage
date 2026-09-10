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
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">
          {errorCount} 错误 · {warningCount} 警告
        </span>
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
            {v.suggestion && (
              <div className="mt-1 italic text-slate-600">建议: {v.suggestion}</div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}