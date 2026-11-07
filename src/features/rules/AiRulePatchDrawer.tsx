import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';

import { rulesApi } from '../../shared/api/rulesApi';
import type {
  PatchApplyResult,
  PatchOperation,
  PatchPreviewResponse,
  RuleEntry,
} from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Textarea } from '../../shared/ui/Textarea';

import { PatchCard } from './PatchCard';

export interface AiRulePatchDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  /** 从单条规则「让 AI 改写这条」进入时的目标条目。 */
  focusEntry?: RuleEntry | null;
  onApplied: () => void;
  onOpenPlaybook?: () => void;
}

/**
 * 可执行 = 无预览错误且不是删除。删除不可撤销，必须用户手动勾选。
 * 导出以便单测，避免把这条安全规则埋在组件内部。
 */
export function initialSelection(operations: PatchOperation[]): Record<string, boolean> {
  return Object.fromEntries(
    operations.map((operation) => [
      operation.opId,
      !operation.error && operation.action !== 'delete',
    ]),
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function AiRulePatchDrawer({
  isOpen,
  onClose,
  projectId,
  focusEntry = null,
  onApplied,
  onOpenPlaybook,
}: AiRulePatchDrawerProps) {
  const { t } = useI18n();
  const prefill = focusEntry ? t('rules.ai.prefill').replace('{content}', focusEntry.content) : '';
  const [instruction, setInstruction] = useState(prefill);
  const [preview, setPreview] = useState<PatchPreviewResponse | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, PatchApplyResult>>({});
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开都从目标条目的预填文案开始，不残留上一轮对话。
  useEffect(() => {
    if (!isOpen) return;
    setInstruction(prefill);
    setPreview(null);
    setSelection({});
    setResults({});
    setError(null);
  }, [isOpen, prefill]);

  const selectedOperations = useMemo(
    () => (preview?.operations ?? []).filter((operation) => selection[operation.opId]),
    [preview, selection],
  );

  const handleGenerate = async () => {
    if (generating || !instruction.trim()) return;
    setGenerating(true);
    setError(null);
    setResults({});
    try {
      const response = await rulesApi.previewPatch(projectId, {
        instruction: instruction.trim(),
        ruleId: focusEntry?.id ?? null,
      });
      setPreview(response);
      setSelection(initialSelection(response.operations));
    } catch (err) {
      setPreview(null);
      setError(t('rules.ai.failed').replace('{message}', errorMessage(err)));
    } finally {
      setGenerating(false);
    }
  };

  const handleApply = async () => {
    if (applying || selectedOperations.length === 0) return;
    setApplying(true);
    setError(null);
    try {
      const response = await rulesApi.applyPatch(projectId, {
        instruction: instruction.trim(),
        operations: selectedOperations,
      });
      const next: Record<string, PatchApplyResult> = {};
      response.results.forEach((item) => {
        next[item.opId] = item;
      });
      setResults(next);
      if (response.applied > 0) {
        onApplied();
        // 已成功的条目退出可选集合，剩下的（冲突/未应用）留给用户再处理。
        setSelection((prev) => {
          const copy = { ...prev };
          response.results.forEach((item) => {
            if (item.status === 'applied') copy[item.opId] = false;
          });
          return copy;
        });
      }
    } catch (err) {
      setError(t('rules.ai.applyFailed').replace('{message}', errorMessage(err)));
    } finally {
      setApplying(false);
    }
  };

  const operations = preview?.operations ?? [];

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-overlay" />
        </Transition.Child>

        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200"
            enterFrom="opacity-0 scale-95"
            enterTo="opacity-100 scale-100"
            leave="ease-in duration-150"
            leaveFrom="opacity-100 scale-100"
            leaveTo="opacity-0 scale-95"
          >
            <Dialog.Panel
              className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-surface-elevated shadow-xl dark:bg-surface"
              data-testid="ai-drawer"
            >
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

              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                <Textarea
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder={t('rules.ai.instructionPlaceholder')}
                  rows={3}
                  data-testid="ai-instruction"
                />

                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleGenerate}
                    disabled={generating || !instruction.trim()}
                    data-testid="ai-generate"
                  >
                    {generating ? t('rules.ai.generating') : t('rules.ai.generate')}
                  </Button>
                  {selectedOperations.length > 0 ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleApply}
                      disabled={applying}
                      data-testid="ai-apply"
                    >
                      {applying
                        ? t('rules.ai.applying')
                        : t('rules.ai.apply').replace('{count}', String(selectedOperations.length))}
                    </Button>
                  ) : null}
                </div>

                {error ? (
                  <p className="text-sm text-error" data-testid="ai-error">
                    {error}
                  </p>
                ) : null}

                {preview?.message ? (
                  <p className="text-sm text-text-secondary" data-testid="ai-message">
                    {preview.message}
                  </p>
                ) : null}

                {!preview && !error ? (
                  <p className="text-sm text-text-tertiary">{t('rules.ai.empty')}</p>
                ) : null}

                {preview && operations.length === 0 && !preview.message ? (
                  <p className="text-sm text-text-tertiary" data-testid="ai-message">
                    {t('rules.ai.noOperations')}
                  </p>
                ) : null}

                {operations.map((operation) => (
                  <PatchCard
                    key={operation.opId}
                    operation={operation}
                    selected={selection[operation.opId] ?? false}
                    disabled={applying}
                    result={results[operation.opId] ?? null}
                    onToggle={(opId, next) => setSelection((prev) => ({ ...prev, [opId]: next }))}
                    onOpenPlaybook={onOpenPlaybook}
                  />
                ))}
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}
