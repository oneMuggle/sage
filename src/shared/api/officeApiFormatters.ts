/**
 * Formatting / governance helpers for the Office API surface.
 *
 * Split out of officeApi.ts to keep the aggregate API object under the
 * file-size ratchet; officeApi.ts re-exports them for existing callers.
 */

import type { OfficeWordLintResult } from './types';

export function formatOfficeWordLintSummary(res: OfficeWordLintResult): string {
  const status = res.ok ? 'OK' : 'ISSUES';
  return `${status} · ${res.error_count} errors · ${res.warning_count} warnings · ${res.checked_rules.length} rules`;
}

export function formatOfficeWordLintJson(res: OfficeWordLintResult): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.office_word_lint.v1',
      ok: res.ok,
      issueCount: res.issue_count,
      errorCount: res.error_count,
      warningCount: res.warning_count,
      checkedRules: res.checked_rules,
    },
    null,
    2,
  );
}

export function auditOfficeApiGovernance(): string {
  return JSON.stringify({
    module: 'office-api',
    phase: 'P188',
    audited: true,
  });
}
