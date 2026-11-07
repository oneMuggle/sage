import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';

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
  onOpenPlaybook?: (operation: PatchOperation) => void;
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

/** IPC 会剥掉自定义错误码，message 文本是渲染侧唯一稳定的兜底信号。 */
function isSchemaError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const code = (error as { code?: unknown }).code;
  return code === 'patch_schema_invalid' || error.message.includes('AI 返回格式不正确');
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
  const [applySummary, setApplySummary] = useState<{ applied: number; failed: number } | null>(
    null,
  );
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 会话纪元：关闭后重开 +1，所有在途请求据此丢弃过期结果。
  const epochRef = useRef(0);
  const sessionOpenedRef = useRef(false);
  const prefillOpenedRef = useRef(false);

  // 只在 isOpen 的关闭→打开跃迁时清空会话状态（语言切换不触发）。
  useEffect(() => {
    if (!isOpen) {
      sessionOpenedRef.current = false;
      return;
    }
    if (sessionOpenedRef.current) return;
    sessionOpenedRef.current = true;
    epochRef.current += 1;
    setPreview(null);
    setSelection({});
    setResults({});
    setApplySummary(null);
    setError(null);
    setGenerating(false);
    setApplying(false);
  }, [isOpen]);

  // 预填文案单独放在打开跃迁里，避免语言切换时覆盖用户正在编辑的指令。
  useEffect(() => {
    if (!isOpen) {
      prefillOpenedRef.current = false;
      return;
    }
    if (prefillOpenedRef.current) return;
    prefillOpenedRef.current = true;
    setInstruction(prefill);
  }, [isOpen, prefill]);

  const selectedOperations = useMemo(
    () => (preview?.operations ?? []).filter((operation) => selection[operation.opId]),
    [preview, selection],
  );

  const handleGenerate = async () => {
    if (generating || applying || !instruction.trim()) return;
    const epoch = epochRef.current;
    setGenerating(true);
    // 新一轮生成前清空旧结果，避免在途期间误选/误提交上一轮的卡片。
    setPreview(null);
    setSelection({});
    setResults({});
    setApplySummary(null);
    setError(null);
    try {
      const response = await rulesApi.previewPatch(projectId, {
        instruction: instruction.trim(),
        ruleId: focusEntry?.id ?? null,
      });
      if (epochRef.current !== epoch) return;
      setPreview(response);
      setSelection(initialSelection(response.operations));
    } catch (err) {
      if (epochRef.current !== epoch) return;
      setPreview(null);
      setError(
        isSchemaError(err)
          ? t('rules.ai.schemaFailed')
          : t('rules.ai.failed').replace('{message}', errorMessage(err)),
      );
    } finally {
      if (epochRef.current === epoch) setGenerating(false);
    }
  };

  const handleApply = async () => {
    if (applying || generating || selectedOperations.length === 0) return;
    const epoch = epochRef.current;
    setApplying(true);
    setError(null);
    setApplySummary(null);
    try {
      const response = await rulesApi.applyPatch(projectId, {
        instruction: instruction.trim(),
        operations: selectedOperations,
      });
      if (epochRef.current !== epoch) return;
      const next: Record<string, PatchApplyResult> = {};
      response.results.forEach((item) => {
        next[item.opId] = item;
      });
      setResults(next);
      setApplySummary({ applied: response.applied, failed: response.failed });
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
      if (epochRef.current !== epoch) return;
      setError(t('rules.ai.applyFailed').replace('{message}', errorMessage(err)));
    } finally {
      if (epochRef.current === epoch) setApplying(false);
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
                  aria-label={t('rules.ai.instructionLabel')}
                  rows={3}
                  data-testid="ai-instruction"
                />

                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleGenerate}
                    disabled={generating || applying || !instruction.trim()}
                    data-testid="ai-generate"
                  >
                    {generating ? t('rules.ai.generating') : t('rules.ai.generate')}
                  </Button>
                  {selectedOperations.length > 0 ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleApply}
                      disabled={applying || generating}
                      data-testid="ai-apply"
                    >
                      {applying
                        ? t('rules.ai.applying')
                        : t('rules.ai.apply').replace('{count}', String(selectedOperations.length))}
                    </Button>
                  ) : null}
                </div>

                {error ? (
                  <p className="text-sm text-error" role="alert" data-testid="ai-error">
                    {error}
                  </p>
                ) : null}

                {preview?.llmAvailable === false ? (
                  <p
                    className="text-sm text-text-secondary"
                    aria-live="polite"
                    data-testid="ai-message"
                  >
                    {t('rules.ai.unavailable')}
                  </p>
                ) : preview?.message ? (
                  <p
                    className="text-sm text-text-secondary"
                    aria-live="polite"
                    data-testid="ai-message"
                  >
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
                    disabled={applying || generating}
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
