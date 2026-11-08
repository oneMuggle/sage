import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment } from 'react';

import type {
  PatchApplyResult,
  PatchOperation,
  PatchPreviewResponse,
  RuleEntry,
} from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Textarea } from '../../shared/ui/Textarea';

import { PatchCard } from './PatchCard';
import { useAiRulePatch } from './useAiRulePatch';

export { initialSelection } from './useAiRulePatch';

export interface AiRulePatchDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  /** 从单条规则「让 AI 改写这条」进入时的目标条目。 */
  focusEntry?: RuleEntry | null;
  onApplied: () => void;
  onOpenPlaybook?: (operation: PatchOperation) => void;
}

function DrawerHeader({
  focusEntry,
  onClose,
}: {
  focusEntry: RuleEntry | null | undefined;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border p-4">
      <div className="space-y-1">
        <Dialog.Title className="text-base font-semibold text-text">
          {t('rules.ai.title')}
        </Dialog.Title>
        <p className="text-sm text-text-secondary">{t('rules.ai.subtitle')}</p>
        {focusEntry ? (
          <p className="text-xs text-text-tertiary">
            {t('rules.ai.focusHint').replace(
              '{label}',
              `${focusEntry.sourceLabel} · ${focusEntry.category}`,
            )}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label={t('rules.ai.close')}
        className="rounded p-1 text-text-secondary hover:bg-hover"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function MessageArea({
  error,
  preview,
  applySummary,
}: {
  error: string | null;
  preview: PatchPreviewResponse | null;
  applySummary: { applied: number; failed: number } | null;
}) {
  const { t } = useI18n();
  return (
    <>
      {error ? (
        <p className="text-sm text-error" role="alert" data-testid="ai-error">
          {error}
        </p>
      ) : null}
      {preview?.llmAvailable === false ? (
        <p className="text-sm text-text-secondary" aria-live="polite" data-testid="ai-message">
          {t('rules.ai.unavailable')}
        </p>
      ) : preview?.message ? (
        <p className="text-sm text-text-secondary" aria-live="polite" data-testid="ai-message">
          {preview.message}
        </p>
      ) : null}
      {applySummary && applySummary.applied > 0 ? (
        <p
          className="text-sm text-text-secondary"
          aria-live="polite"
          data-testid="ai-apply-summary"
        >
          {applySummary.failed > 0
            ? t('rules.ai.partial')
                .replace('{applied}', String(applySummary.applied))
                .replace('{failed}', String(applySummary.failed))
            : t('rules.ai.applied').replace('{count}', String(applySummary.applied))}
        </p>
      ) : null}
    </>
  );
}

function OperationList({
  operations,
  selection,
  applying,
  generating,
  results,
  onToggle,
  onOpenPlaybook,
}: {
  operations: PatchOperation[];
  selection: Record<string, boolean>;
  applying: boolean;
  generating: boolean;
  results: Record<string, PatchApplyResult>;
  onToggle: (opId: string, next: boolean) => void;
  onOpenPlaybook?: (operation: PatchOperation) => void;
}) {
  return (
    <>
      {operations.map((operation) => (
        <PatchCard
          key={operation.opId}
          operation={operation}
          selected={selection[operation.opId] ?? false}
          disabled={applying || generating}
          result={results[operation.opId] ?? null}
          onToggle={onToggle}
          onOpenPlaybook={onOpenPlaybook}
        />
      ))}
    </>
  );
}

function ActionBar({
  hook,
  t,
}: {
  hook: ReturnType<typeof useAiRulePatch>;
  t: (key: TranslationKey) => string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="primary"
        size="sm"
        onClick={hook.handleGenerate}
        disabled={hook.generating || hook.applying || !hook.instruction.trim()}
        data-testid="ai-generate"
      >
        {hook.generating ? t('rules.ai.generating') : t('rules.ai.generate')}
      </Button>
      {hook.selectedOperations.length > 0 ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={hook.handleApply}
          disabled={hook.applying || hook.generating}
          data-testid="ai-apply"
        >
          {hook.applying
            ? t('rules.ai.applying')
            : t('rules.ai.apply').replace('{count}', String(hook.selectedOperations.length))}
        </Button>
      ) : null}
    </div>
  );
}

function DrawerBody({
  hook,
  onOpenPlaybook,
}: {
  hook: ReturnType<typeof useAiRulePatch>;
  onOpenPlaybook?: (operation: PatchOperation) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex-1 space-y-3 overflow-y-auto p-4">
      <Textarea
        value={hook.instruction}
        onChange={(event) => hook.setInstruction(event.target.value)}
        placeholder={t('rules.ai.instructionPlaceholder')}
        aria-label={t('rules.ai.instructionLabel')}
        rows={3}
        data-testid="ai-instruction"
      />
      <ActionBar hook={hook} t={t} />
      <MessageArea error={hook.error} preview={hook.preview} applySummary={hook.applySummary} />
      {!hook.preview && !hook.error ? (
        <p className="text-sm text-text-tertiary">{t('rules.ai.empty')}</p>
      ) : null}
      {hook.preview && hook.operations.length === 0 && !hook.preview.message ? (
        <p className="text-sm text-text-tertiary" data-testid="ai-message">
          {t('rules.ai.noOperations')}
        </p>
      ) : null}
      <OperationList
        operations={hook.operations}
        selection={hook.selection}
        applying={hook.applying}
        generating={hook.generating}
        results={hook.results}
        onToggle={(opId, next) => hook.setSelection((prev) => ({ ...prev, [opId]: next }))}
        onOpenPlaybook={onOpenPlaybook}
      />
    </div>
  );
}

export function AiRulePatchDrawer({
  isOpen,
  onClose,
  projectId,
  focusEntry = null,
  onApplied,
  onOpenPlaybook,
}: AiRulePatchDrawerProps) {
  const hook = useAiRulePatch(projectId, isOpen, focusEntry, onApplied);

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100" leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0">
          <div className="fixed inset-0 bg-overlay" />
        </Transition.Child>
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100" leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95">
            <Dialog.Panel
              className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-surface-elevated shadow-xl dark:bg-surface"
              data-testid="ai-drawer"
            >
              <DrawerHeader focusEntry={focusEntry} onClose={onClose} />
              <DrawerBody hook={hook} onOpenPlaybook={onOpenPlaybook} />
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}
