// src/features/office/rules/RuleDetailPanel.tsx
import { useState } from 'react';

import { useI18n } from '../../../shared/lib/i18n';

import type {
  Rule,
  RuleCheckMode,
  RuleFields,
  RuleGroup,
  RuleScope,
  RuleSeverity,
  RuleType,
} from './ruleTypes';
import { RULE_CHECK_MODES, RULE_SCOPES, RULE_SEVERITIES, RULE_TYPES } from './ruleTypes';

export interface RuleDetailPanelProps {
  group: RuleGroup | null;
  rule: Rule | null;
  busy: boolean;
  onCreate: (fields: RuleFields) => void | Promise<void>;
  onUpdate: (ruleId: string, fields: Partial<RuleFields>) => void | Promise<void>;
  onDelete: (ruleId: string) => void | Promise<void>;
}

const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

function ruleToFields(rule: Rule | null): RuleFields {
  return {
    name: rule?.name ?? '',
    type: rule?.type ?? 'custom',
    severity: rule?.severity ?? 'warning',
    scope: rule?.scope ?? 'full',
    checkMode: rule?.checkMode ?? 'regex',
    description: rule?.description ?? '',
    pattern: rule?.pattern ?? '',
    aiPrompt: rule?.aiPrompt ?? '',
    enabled: rule?.enabled ?? true,
  };
}

export function RuleDetailPanel({
  group,
  rule,
  busy,
  onCreate,
  onUpdate,
  onDelete,
}: RuleDetailPanelProps) {
  const { t } = useI18n();
  const initial = ruleToFields(rule);
  const [name, setName] = useState(initial.name);
  const [type, setType] = useState<RuleType>(initial.type);
  const [severity, setSeverity] = useState<RuleSeverity>(initial.severity);
  const [scope, setScope] = useState<RuleScope>(initial.scope);
  const [checkMode, setCheckMode] = useState<RuleCheckMode>(initial.checkMode);
  const [description, setDescription] = useState(initial.description);
  const [pattern, setPattern] = useState(initial.pattern ?? '');
  const [aiPrompt, setAiPrompt] = useState(initial.aiPrompt ?? '');
  const [enabled, setEnabled] = useState(initial.enabled);
  const [error, setError] = useState<string | null>(null);

  if (!group) {
    return (
      <section
        className="rounded border border-border bg-bg-subtle p-3"
        data-testid="rule-detail-panel"
      >
        <p className="text-xs text-muted">{t('office.rules.detail.noGroupHint')}</p>
      </section>
    );
  }

  const validate = (): string | null => {
    if (!name.trim()) return t('office.rules.detail.nameRequired');
    if (checkMode === 'regex' && !pattern.trim()) return t('office.rules.detail.patternRequired');
    if (checkMode === 'ai' && !aiPrompt.trim()) return t('office.rules.detail.aiPromptRequired');
    return null;
  };

  const submit = () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    const fields: RuleFields = {
      name: name.trim(),
      type,
      severity,
      scope,
      description: description.trim(),
      checkMode,
      pattern: checkMode === 'regex' ? pattern.trim() : '',
      aiPrompt: checkMode === 'ai' ? aiPrompt.trim() : '',
      enabled,
    };
    if (rule) {
      void onUpdate(rule.id, fields);
    } else {
      void onCreate(fields);
    }
  };

  return (
    <section className="space-y-3" data-testid="rule-detail-panel">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-secondary">
          {t('office.rules.detail.title')}
        </h3>
        {rule ? (
          <button
            type="button"
            data-testid="rule-detail-delete"
            className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
            disabled={busy}
            onClick={() => {
              if (!window.confirm(`${t('office.rules.detail.confirmDelete')} (${rule.name})`))
                return;
              void onDelete(rule.id);
            }}
          >
            {t('office.rules.detail.delete')}
          </button>
        ) : null}
      </div>

      <div className="space-y-2 rounded border border-border bg-bg-subtle p-3">
        <label className="block space-y-1">
          <span className="text-xs text-text-secondary">{t('office.rules.detail.name')}</span>
          <input
            className={inputClass}
            data-testid="rule-detail-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">{t('office.rules.detail.type')}</span>
            <select
              className={inputClass}
              data-testid="rule-detail-type"
              value={type}
              onChange={(e) => setType(e.target.value as RuleType)}
            >
              {RULE_TYPES.map((value) => (
                <option key={value} value={value}>
                  {t(`office.rules.type.${value}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">{t('office.rules.detail.severity')}</span>
            <select
              className={inputClass}
              data-testid="rule-detail-severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as RuleSeverity)}
            >
              {RULE_SEVERITIES.map((value) => (
                <option key={value} value={value}>
                  {t(`office.rules.severity.${value}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">{t('office.rules.detail.scope')}</span>
            <select
              className={inputClass}
              data-testid="rule-detail-scope"
              value={scope}
              onChange={(e) => setScope(e.target.value as RuleScope)}
            >
              {RULE_SCOPES.map((value) => (
                <option key={value} value={value}>
                  {t(`office.rules.scope.${value}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">
              {t('office.rules.detail.checkMode')}
            </span>
            <select
              className={inputClass}
              data-testid="rule-detail-check-mode"
              value={checkMode}
              onChange={(e) => setCheckMode(e.target.value as RuleCheckMode)}
            >
              {RULE_CHECK_MODES.map((value) => (
                <option key={value} value={value}>
                  {t(`office.rules.checkMode.${value}`)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-xs text-text-secondary">
            {t('office.rules.detail.description')}
          </span>
          <textarea
            className={`${inputClass} min-h-[80px]`}
            data-testid="rule-detail-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        {checkMode === 'regex' ? (
          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">{t('office.rules.detail.pattern')}</span>
            <input
              className={inputClass}
              data-testid="rule-detail-pattern"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
            />
          </label>
        ) : (
          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">{t('office.rules.detail.aiPrompt')}</span>
            <textarea
              className={`${inputClass} min-h-[80px]`}
              data-testid="rule-detail-ai-prompt"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
            />
          </label>
        )}

        <label className="flex items-center gap-2 text-xs text-text">
          <input
            type="checkbox"
            data-testid="rule-detail-enabled"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {t('office.rules.detail.enabled')}
        </label>

        {error ? (
          <p className="text-xs text-error" data-testid="rule-detail-error">
            {error}
          </p>
        ) : null}

        <div className="flex gap-2">
          <button
            type="button"
            data-testid="rule-detail-save"
            className="rounded bg-primary px-3 py-1.5 text-sm text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            disabled={busy}
            onClick={submit}
          >
            {t('office.rules.detail.save')}
          </button>
          {rule ? (
            <button
              type="button"
              data-testid="rule-detail-cancel"
              className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover"
              onClick={() => {
                const reset = ruleToFields(rule);
                setName(reset.name);
                setType(reset.type);
                setSeverity(reset.severity);
                setScope(reset.scope);
                setCheckMode(reset.checkMode);
                setDescription(reset.description);
                setPattern(reset.pattern ?? '');
                setAiPrompt(reset.aiPrompt ?? '');
                setEnabled(reset.enabled);
                setError(null);
              }}
            >
              {t('office.rules.detail.cancel')}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
