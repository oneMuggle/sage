import { Lock } from 'lucide-react';

import type { PatchApplyResult, PatchOperation } from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Badge } from '../../shared/ui/Badge';

import { MAX_RULE_CHARS } from './RuleEditorDialog';
import { layerLabelKey } from './rulesView';

const ACTION_KEYS = {
  add: 'rules.ai.action.add',
  update: 'rules.ai.action.update',
  delete: 'rules.ai.action.delete',
  toggle: 'rules.ai.action.toggle',
} as const;

const ERROR_KEYS = {
  readonly_layer: 'rules.ai.readonly',
  rule_not_found: 'rules.ai.error.rule_not_found',
  empty_content: 'rules.ai.error.empty_content',
  content_too_long: 'rules.ai.error.content_too_long',
  invalid_patch: 'rules.ai.error.invalid_patch',
} as const;

const STATUS_KEYS = {
  applied: 'rules.ai.status.applied',
  invalid: 'rules.ai.status.invalid',
  conflict: 'rules.ai.status.conflict',
} as const;

const STATUS_VARIANTS = {
  applied: 'secondary',
  invalid: 'outline',
  conflict: 'destructive',
} as const;

export interface PatchCardProps {
  operation: PatchOperation;
  selected: boolean;
  disabled?: boolean;
  result?: PatchApplyResult | null;
  onToggle?: (opId: string, selected: boolean) => void;
  /** 只读层（规程）改动的跳转入口。 */
  onOpenPlaybook?: (operation: PatchOperation) => void;
}

function readContent(value: Record<string, unknown>): string {
  return typeof value.content === 'string' ? value.content : '';
}

/** toggle 类操作没有 content，用 before/after.enabled 表达目标状态。 */
function describeChange(operation: PatchOperation): string | null {
  const content = readContent(operation.after);
  if (content) return content;
  if (operation.action !== 'toggle') return null;
  return operation.after.enabled === true ? 'toggle.on' : 'toggle.off';
}

export function PatchCard({
  operation,
  selected,
  disabled = false,
  result = null,
  onToggle,
  onOpenPlaybook,
}: PatchCardProps) {
  const { t } = useI18n();
  const before = readContent(operation.before);
  const change = describeChange(operation);
  const isReadonly = operation.error === 'readonly_layer';
  const errorKey =
    operation.error && operation.error in ERROR_KEYS
      ? ERROR_KEYS[operation.error as keyof typeof ERROR_KEYS]
      : null;
  const errorMessage = errorKey
    ? t(errorKey).replace('{max}', String(MAX_RULE_CHARS))
    : operation.error;
  // 每张卡片的勾选框都要能区分具体操作，而不是同名复选框。
  const selectLabel =
    [t(ACTION_KEYS[operation.action]), operation.ruleId || before || change]
      .filter(Boolean)
      .join(' · ') || t('rules.ai.select');

  return (
    <div
      data-testid={`patch-card-${operation.opId}`}
      className="space-y-2 rounded-lg border border-border bg-surface p-3"
    >
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={selected}
          disabled={disabled || Boolean(operation.error)}
          onChange={(event) => onToggle?.(operation.opId, event.target.checked)}
          aria-label={selectLabel}
          data-testid={`patch-select-${operation.opId}`}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary">{t(layerLabelKey(operation.layer))}</Badge>
            <Badge variant="outline">{t(ACTION_KEYS[operation.action])}</Badge>
            {isReadonly ? (
              <Lock className="h-3.5 w-3.5 text-text-tertiary" aria-hidden="true" />
            ) : null}
            {result ? (
              <Badge
                variant={STATUS_VARIANTS[result.status]}
                data-testid={`patch-result-${operation.opId}`}
              >
                {t(STATUS_KEYS[result.status])}
              </Badge>
            ) : null}
          </div>

          {before && operation.action !== 'add' ? (
            <p
              className="break-words text-sm text-text-secondary line-through"
              data-testid={`patch-before-${operation.opId}`}
            >
              {before}
            </p>
          ) : null}

          {change && operation.action !== 'delete' ? (
            <p
              className="break-words text-sm text-text"
              data-testid={`patch-after-${operation.opId}`}
            >
              {change === 'toggle.on'
                ? t('rules.ai.toggle.on')
                : change === 'toggle.off'
                  ? t('rules.ai.toggle.off')
                  : change}
            </p>
          ) : null}

          {operation.reason ? (
            <p className="text-xs text-text-tertiary">
              {t('rules.ai.reason')}: {operation.reason}
            </p>
          ) : null}

          {operation.action === 'delete' ? (
            <p className="text-xs text-warning">{t('rules.ai.deleteHint')}</p>
          ) : null}

          {errorMessage ? (
            <p className="text-xs text-error" data-testid={`patch-error-${operation.opId}`}>
              {errorMessage}
            </p>
          ) : null}

          {isReadonly && onOpenPlaybook ? (
            <button
              type="button"
              onClick={() => onOpenPlaybook(operation)}
              className="text-xs text-accent underline"
              data-testid={`patch-open-playbook-${operation.opId}`}
            >
              {t('rules.ai.openPlaybook')}
            </button>
          ) : null}

          {result?.status === 'conflict' && result.current ? (
            <p
              className="break-words text-xs text-error"
              data-testid={`patch-current-${operation.opId}`}
            >
              {t('rules.ai.current')}:{' '}
              {readContent(result.current) || JSON.stringify(result.current)}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
