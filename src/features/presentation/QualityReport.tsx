/**
 * QualityReport — 展示一次演示文稿渲染的质量门禁结果。
 *
 * 数据来自 /api/v1/presentation/render-svgs 的 RenderResponse：
 *   success / quality_passed / blocking_errors / warnings / summary / message。
 * 质量门禁不通过时后端不会产出文件，这里要明确区分「阻塞问题」与
 * 「非阻塞警告」，让调用方知道该修什么、而不是只看到一句失败。
 */

import type { PresentationIssue } from '../../shared/api/presentationApi';

export interface QualityReportProps {
  success: boolean;
  qualityPassed: boolean;
  blockingErrors: PresentationIssue[];
  warnings: PresentationIssue[];
  summary: Record<string, unknown>;
  message: string;
  outputPath?: string | null;
  templatesApplied?: string[];
}

const MAX_VISIBLE_ISSUES = 50;

function readNumber(source: Record<string, unknown>, key: string): number | null {
  const value = source[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function issueText(issue: PresentationIssue): string {
  const parts: string[] = [];
  if (typeof issue.code === 'string' && issue.code) parts.push(issue.code);
  if (typeof issue.message === 'string' && issue.message) parts.push(issue.message);
  if (parts.length > 0) return parts.join(' · ');
  if (typeof issue.file === 'string' && issue.file) return issue.file;
  try {
    return JSON.stringify(issue);
  } catch {
    return String(issue);
  }
}

function IssueList({
  issues,
  tone,
  testId,
}: {
  issues: PresentationIssue[];
  tone: 'error' | 'warning';
  testId: string;
}) {
  if (issues.length === 0) return null;
  const visible = issues.slice(0, MAX_VISIBLE_ISSUES);
  const hidden = issues.length - visible.length;
  const containerClass =
    tone === 'error'
      ? 'border-error/30 bg-error/5 text-error'
      : 'border-warning/30 bg-warning/5 text-warning';

  return (
    <div className={`rounded border px-3 py-2 text-xs ${containerClass}`} data-testid={testId}>
      <ul className="space-y-1">
        {visible.map((issue, index) => (
          <li key={index} className="break-words">
            {issueText(issue)}
          </li>
        ))}
      </ul>
      {hidden > 0 ? <p className="mt-1 opacity-80">…另有 {hidden} 条未显示</p> : null}
    </div>
  );
}

export function QualityReport({
  success,
  qualityPassed,
  blockingErrors,
  warnings,
  summary,
  message,
  outputPath,
  templatesApplied,
}: QualityReportProps) {
  const total = readNumber(summary, 'total');
  const passed = readNumber(summary, 'passed');
  const warningCount = readNumber(summary, 'warnings');
  const errorCount = readNumber(summary, 'errors');

  const statusLabel = success ? '生成成功' : qualityPassed ? '生成未完成' : '质量门禁未通过';

  return (
    <div className="space-y-3" data-testid="presentation-quality-report">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            success
              ? 'bg-success/10 text-success'
              : qualityPassed
                ? 'bg-warning/10 text-warning'
                : 'bg-error/10 text-error'
          }`}
          data-testid="presentation-quality-status"
        >
          {statusLabel}
        </span>
        {total !== null ? (
          <span className="text-xs text-muted" data-testid="presentation-quality-summary">
            共 {total} 页{passed !== null ? ` · 通过 ${passed}` : ''}
            {warningCount !== null ? ` · 警告 ${warningCount}` : ''}
            {errorCount !== null ? ` · 错误 ${errorCount}` : ''}
          </span>
        ) : null}
      </div>

      {message ? (
        <p className="text-xs text-text-secondary" data-testid="presentation-quality-message">
          {message}
        </p>
      ) : null}

      <IssueList issues={blockingErrors} tone="error" testId="presentation-quality-blocking" />

      {qualityPassed ? (
        <IssueList issues={warnings} tone="warning" testId="presentation-quality-warnings" />
      ) : null}

      {templatesApplied && templatesApplied.length > 0 ? (
        <p className="text-xs text-text-secondary" data-testid="presentation-quality-templates">
          已应用模板：{templatesApplied.join('、')}
        </p>
      ) : null}

      {success && outputPath ? (
        <div className="text-xs text-text-secondary" data-testid="presentation-quality-output">
          输出文件：<code className="break-all">{outputPath}</code>
        </div>
      ) : null}

      {!qualityPassed ? (
        <p className="text-xs text-muted">存在阻塞问题时不会产出文件，请修复上述问题后重试。</p>
      ) : null}
    </div>
  );
}
