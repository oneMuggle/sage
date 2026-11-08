import { useEffect, useMemo, useRef, useState } from 'react';

import { rulesApi } from '../../shared/api/rulesApi';
import type {
  PatchApplyResult,
  PatchOperation,
  PatchPreviewResponse,
  RuleEntry,
} from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

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

export interface AiRulePatchHookResult {
  instruction: string;
  setInstruction: (value: string) => void;
  preview: PatchPreviewResponse | null;
  selection: Record<string, boolean>;
  setSelection: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  results: Record<string, PatchApplyResult>;
  applySummary: { applied: number; failed: number } | null;
  generating: boolean;
  applying: boolean;
  error: string | null;
  selectedOperations: PatchOperation[];
  operations: PatchOperation[];
  handleGenerate: () => Promise<void>;
  handleApply: () => Promise<void>;
}

export function useAiRulePatch(
  projectId: string,
  isOpen: boolean,
  focusEntry: RuleEntry | null | undefined,
  onApplied: () => void,
): AiRulePatchHookResult {
  const { t } = useI18n();
  const state = usePatchState(isOpen);
  const prefill = focusEntry ? t('rules.ai.prefill').replace('{content}', focusEntry.content) : '';
  usePrefill(isOpen, prefill, state.prefillOpenedRef, state.setInstruction);
  const result = usePatchCompute(projectId, focusEntry, state, onApplied, t);
  return { ...state, ...result, operations: state.preview?.operations ?? [] };
}

interface PatchStateBag {
  instruction: string;
  setInstruction: (value: string) => void;
  preview: PatchPreviewResponse | null;
  setPreview: (v: PatchPreviewResponse | null) => void;
  selection: Record<string, boolean>;
  setSelection: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  results: Record<string, PatchApplyResult>;
  setResults: (v: Record<string, PatchApplyResult>) => void;
  applySummary: { applied: number; failed: number } | null;
  setApplySummary: (v: { applied: number; failed: number } | null) => void;
  generating: boolean;
  setGenerating: (v: boolean) => void;
  applying: boolean;
  setApplying: (v: boolean) => void;
  error: string | null;
  setError: (v: string | null) => void;
  epochRef: React.MutableRefObject<number>;
  sessionOpenedRef: React.MutableRefObject<boolean>;
  prefillOpenedRef: React.MutableRefObject<boolean>;
}

function usePatchState(isOpen: boolean): PatchStateBag {
  const [instruction, setInstruction] = useState('');
  const [preview, setPreview] = useState<PatchPreviewResponse | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, PatchApplyResult>>({});
  const [applySummary, setApplySummary] = useState<{ applied: number; failed: number } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const epochRef = useRef(0);
  const sessionOpenedRef = useRef(false);
  const prefillOpenedRef = useRef(false);
  useSessionReset(isOpen, {
    epochRef, sessionOpenedRef, setPreview, setSelection, setResults,
    setApplySummary, setError, setGenerating, setApplying,
  });
  return {
    instruction, setInstruction, preview, setPreview, selection, setSelection,
    results, setResults, applySummary, setApplySummary, generating, setGenerating,
    applying, setApplying, error, setError, epochRef, sessionOpenedRef, prefillOpenedRef,
  };
}

interface PatchComputeResult {
  selectedOperations: PatchOperation[];
  handleGenerate: () => Promise<void>;
  handleApply: () => Promise<void>;
}

function usePatchCompute(
  projectId: string,
  focusEntry: RuleEntry | null | undefined,
  state: PatchStateBag,
  onApplied: () => void,
  t: (key: TranslationKey) => string,
): PatchComputeResult {
  const selectedOperations = useMemo(
    () => (state.preview?.operations ?? []).filter((op) => state.selection[op.opId]),
    [state.preview, state.selection],
  );
  const handleGenerate = useGenerateHandler(projectId, focusEntry, state, t);
  const handleApply = useApplyHandler(projectId, state, selectedOperations, onApplied, t);
  return { selectedOperations, handleGenerate, handleApply };
}

interface SessionResetDeps {
  epochRef: React.MutableRefObject<number>;
  sessionOpenedRef: React.MutableRefObject<boolean>;
  setPreview: (v: PatchPreviewResponse | null) => void;
  setSelection: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setResults: (v: Record<string, PatchApplyResult>) => void;
  setApplySummary: (v: { applied: number; failed: number } | null) => void;
  setError: (v: string | null) => void;
  setGenerating: (v: boolean) => void;
  setApplying: (v: boolean) => void;
}

function useSessionReset(isOpen: boolean, deps: SessionResetDeps) {
  const depsRef = useRef(deps);
  depsRef.current = deps;
  useEffect(() => {
    const d = depsRef.current;
    if (!isOpen) {
      d.sessionOpenedRef.current = false;
      return;
    }
    if (d.sessionOpenedRef.current) return;
    d.sessionOpenedRef.current = true;
    d.epochRef.current += 1;
    d.setPreview(null);
    d.setSelection({});
    d.setResults({});
    d.setApplySummary(null);
    d.setError(null);
    d.setGenerating(false);
    d.setApplying(false);
  }, [isOpen]);
}

function usePrefill(
  isOpen: boolean,
  prefill: string,
  prefillOpenedRef: React.MutableRefObject<boolean>,
  setInstruction: (value: string) => void,
) {
  useEffect(() => {
    if (!isOpen) {
      prefillOpenedRef.current = false;
      return;
    }
    if (prefillOpenedRef.current) return;
    prefillOpenedRef.current = true;
    setInstruction(prefill);
  }, [isOpen, prefill, prefillOpenedRef, setInstruction]);
}

function useGenerateHandler(
  projectId: string,
  focusEntry: RuleEntry | null | undefined,
  state: PatchStateBag,
  t: (key: TranslationKey) => string,
): () => Promise<void> {
  return async () => {
    if (state.generating || state.applying || !state.instruction.trim()) return;
    const epoch = state.epochRef.current;
    state.setGenerating(true);
    state.setPreview(null);
    state.setSelection({});
    state.setResults({});
    state.setApplySummary(null);
    state.setError(null);
    try {
      const response = await rulesApi.previewPatch(projectId, {
        instruction: state.instruction.trim(),
        ruleId: focusEntry?.id ?? null,
      });
      if (state.epochRef.current !== epoch) return;
      state.setPreview(response);
      state.setSelection(initialSelection(response.operations));
    } catch (err) {
      if (state.epochRef.current !== epoch) return;
      state.setPreview(null);
      state.setError(
        isSchemaError(err)
          ? t('rules.ai.schemaFailed')
          : t('rules.ai.failed').replace('{message}', errorMessage(err)),
      );
    } finally {
      if (state.epochRef.current === epoch) state.setGenerating(false);
    }
  };
}

function useApplyHandler(
  projectId: string,
  state: PatchStateBag,
  selectedOperations: PatchOperation[],
  onApplied: () => void,
  t: (key: TranslationKey) => string,
): () => Promise<void> {
  return async () => {
    if (state.applying || state.generating || selectedOperations.length === 0) return;
    const epoch = state.epochRef.current;
    state.setApplying(true);
    state.setError(null);
    state.setApplySummary(null);
    try {
      const response = await rulesApi.applyPatch(projectId, {
        instruction: state.instruction.trim(),
        operations: selectedOperations,
      });
      if (state.epochRef.current !== epoch) return;
      const next: Record<string, PatchApplyResult> = {};
      response.results.forEach((item) => {
        next[item.opId] = item;
      });
      state.setResults(next);
      state.setApplySummary({ applied: response.applied, failed: response.failed });
      if (response.applied > 0) {
        onApplied();
        state.setSelection((prev) => {
          const copy = { ...prev };
          response.results.forEach((item) => {
            if (item.status === 'applied') copy[item.opId] = false;
          });
          return copy;
        });
      }
    } catch (err) {
      if (state.epochRef.current !== epoch) return;
      state.setError(t('rules.ai.applyFailed').replace('{message}', errorMessage(err)));
    } finally {
      if (state.epochRef.current === epoch) state.setApplying(false);
    }
  };
}
