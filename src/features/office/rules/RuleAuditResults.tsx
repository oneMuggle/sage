// src/features/office/rules/RuleAuditResults.tsx
import { useI18n } from '../../../shared/lib/i18n';

import type { RuleAuditResult } from './ruleTypes';

export interface RuleAuditResultsProps {
  result: RuleAuditResult | null;
  auditing: boolean;
}

export function RuleAuditResults({ result, auditing }: RuleAuditResultsProps) {
  const { t } = useI18n();

  if (auditing) {
    return (
      <section
        className="rounded border border-border bg-bg-subtle p-3 text-xs text-muted"
        data-testid="rule-audit-loading"
      >
        {t('office.rules.workspace.auditing')}
      </section>
    );
  }

  if (!result) {
    return (
      <section
        className="rounded border border-border bg-bg-subtle p-3 text-xs text-muted"
        data-testid="rule-audit-empty"
      >
        {t('office.rules.audit.empty')}
      </section>
    );
  }

  if (result.findings.length === 0) {
    return (
      <section
        className="rounded border border-border bg-bg-subtle p-3 text-xs text-muted"
        data-testid="rule-audit-empty"
      >
        {t('office.rules.audit.empty')}
      </section>
    );
  }

  return (
    <section className="space-y-2" data-testid="rule-audit-results">
      <div className="flex flex-wrap gap-3 text-xs text-text-secondary">
        <span>
          {t('office.rules.audit.errors')}: {result.errorCount}
        </span>
        <span>
          {t('office.rules.audit.warnings')}: {result.warningCount}
        </span>
        <span>
          {t('office.rules.audit.infos')}: {result.infoCount}
        </span>
      </div>
      <ul className="space-y-2">
        {result.findings.map((finding, index) => (
          <li
            key={`${finding.ruleId}-${index}`}
            data-testid={`rule-audit-finding-${finding.ruleId}-${index}`}
            className="rounded border border-border bg-bg-subtle p-3 text-xs text-text"
          >
            <p className="font-medium">{finding.ruleName}</p>
            <p className="text-text-secondary">
              {t(`office.rules.severity.${finding.severity}`)} · {finding.location}
            </p>
            <p className="mt-1">{finding.message}</p>
            {finding.suggestion ? (
              <p className="mt-1 text-muted">
                {t('office.rules.audit.suggestion')}: {finding.suggestion}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
