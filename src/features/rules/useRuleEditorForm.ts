// src/features/rules/useRuleEditorForm.ts
/** 规则编辑器表单状态与副作用；拆成若干小 hook 以满足「函数 < 50 行」。 */
import { useEffect, useState } from 'react';

import {
  rulesApi,
  type CreatableRuleLayer,
  type RawRulesResponse,
  type RuleEntry,
} from '../../shared/api/rulesApi';
import type { TranslationKey } from '../../shared/lib/i18n';

import { isConflictError } from './rulesView';

export type Translate = (key: TranslationKey) => string;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface RuleEditorFormInput {
  isOpen: boolean;
  projectId: string;
  entry: RuleEntry | null;
  initialLayer: CreatableRuleLayer;
  maxChars: number;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
  t: Translate;
}

export interface EditorFields {
  layer: CreatableRuleLayer;
  category: string;
  content: string;
  trigger: string;
  priority: number;
  enabled: boolean;
  handleLayerChange: (next: string) => void;
  setCategory: (value: string) => void;
  setContent: (value: string) => void;
  setTrigger: (value: string) => void;
  setPriority: (value: number) => void;
  setEnabled: (value: boolean) => void;
}

export interface RuleEditorFormState extends EditorFields {
  isEdit: boolean;
  saving: boolean;
  error: string | null;
  conflictCurrent: RuleEntry | null;
  rawPreview: RawRulesResponse | null;
  rawLoading: boolean;
  tooLong: boolean;
  canSave: boolean;
  handleSave: () => Promise<void>;
  handleToggleRaw: () => Promise<void>;
  handleUseServer: () => void;
}

interface PersistInput {
  projectId: string;
  entry: RuleEntry | null;
  layer: CreatableRuleLayer;
  category: string;
  content: string;
  trigger: string;
  priority: number;
  enabled: boolean;
  /** 冲突后「使用服务器版本」时覆盖 `entry.updatedAt`。 */
  expectedUpdatedAt?: number | null;
}

/** 新建 / 编辑的实际请求；编辑只提交该层支持的字段。 */
async function persistRule(input: PersistInput): Promise<void> {
  const { projectId, entry, layer, category, content, trigger, priority, enabled } = input;
  if (!entry) {
    await rulesApi.create(projectId, {
      layer,
      category: category.trim() || undefined,
      content,
      triggerPattern: layer === 'constraint' ? trigger.trim() || null : null,
      priority,
      enabled,
    });
    return;
  }
  if (layer === 'constraint') {
    await rulesApi.update(projectId, {
      layer,
      ruleId: entry.id,
      patch: {
        content,
        category: category.trim(),
        triggerPattern: trigger.trim(),
        priority,
        enabled,
      },
      expectedUpdatedAt: input.expectedUpdatedAt ?? entry.updatedAt,
    });
    return;
  }
  await rulesApi.update(projectId, { layer, ruleId: entry.id, patch: { content } });
}

function defaultCategoryFor(layer: CreatableRuleLayer, t: Translate): string {
  return layer === 'constraint'
    ? t('rules.editor.defaultCategory')
    : t('rules.editor.defaultSection');
}

function useEditorFields({
  isOpen,
  entry,
  initialLayer,
  t,
}: Pick<RuleEditorFormInput, 'isOpen' | 'entry' | 'initialLayer' | 't'>): EditorFields {
  const [layer, setLayer] = useState<CreatableRuleLayer>(initialLayer);
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [trigger, setTrigger] = useState('');
  const [priority, setPriority] = useState(5);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!isOpen) return;
    const nextLayer: CreatableRuleLayer =
      entry && entry.layer !== 'playbook' ? entry.layer : initialLayer;
    setLayer(nextLayer);
    setCategory(entry?.category ?? defaultCategoryFor(nextLayer, t));
    setContent(entry?.content ?? '');
    setTrigger(entry?.trigger ?? '');
    setPriority(entry?.priority ?? 5);
    setEnabled(entry?.enabled ?? true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在打开/切换目标时重置
  }, [isOpen, entry, initialLayer]);

  const handleLayerChange = (next: string) => {
    const nextLayer = next as CreatableRuleLayer;
    setLayer(nextLayer);
    if (!entry) setCategory(defaultCategoryFor(nextLayer, t));
  };

  return {
    layer,
    category,
    content,
    trigger,
    priority,
    enabled,
    handleLayerChange,
    setCategory,
    setContent,
    setTrigger,
    setPriority,
    setEnabled,
  };
}

interface UseRawPreviewInput {
  isOpen: boolean;
  projectId: string;
  layer: CreatableRuleLayer;
  t: Translate;
  setError: (message: string | null) => void;
}

function useRawPreview({ isOpen, projectId, layer, t, setError }: UseRawPreviewInput) {
  const [rawPreview, setRawPreview] = useState<RawRulesResponse | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setRawPreview(null);
    setRawLoading(false);
  }, [isOpen]);

  const handleToggleRaw = async () => {
    if (rawPreview) {
      setRawPreview(null);
      return;
    }
    setRawLoading(true);
    setError(null);
    try {
      setRawPreview(await rulesApi.raw(projectId, layer));
    } catch (err) {
      setError(t('rules.editor.rawFailed').replace('{message}', errorMessage(err)));
    } finally {
      setRawLoading(false);
    }
  };

  return { rawPreview, rawLoading, handleToggleRaw };
}

interface UseConflictRecoveryInput {
  isOpen: boolean;
  projectId: string;
  entry: RuleEntry | null;
  fields: EditorFields;
  clearError: () => void;
}

function useConflictRecovery({
  isOpen,
  projectId,
  entry,
  fields,
  clearError,
}: UseConflictRecoveryInput) {
  const [conflictCurrent, setConflictCurrent] = useState<RuleEntry | null>(null);
  const [expectedUpdatedAtOverride, setExpectedUpdatedAtOverride] = useState<number | undefined>();

  useEffect(() => {
    if (!isOpen) return;
    setConflictCurrent(null);
    setExpectedUpdatedAtOverride(undefined);
  }, [isOpen, entry]);

  const refreshConflict = async (target: RuleEntry) => {
    try {
      const list = await rulesApi.list(projectId);
      setConflictCurrent(list.find((item) => item.id === target.id) ?? null);
    } catch {
      setConflictCurrent(null);
    }
  };

  const handleUseServer = () => {
    if (!conflictCurrent) return;
    fields.setCategory(conflictCurrent.category);
    fields.setContent(conflictCurrent.content);
    fields.setTrigger(conflictCurrent.trigger ?? '');
    fields.setPriority(conflictCurrent.priority);
    fields.setEnabled(conflictCurrent.enabled);
    setExpectedUpdatedAtOverride(conflictCurrent.updatedAt ?? undefined);
    setConflictCurrent(null);
    clearError();
  };

  return { conflictCurrent, expectedUpdatedAtOverride, refreshConflict, handleUseServer };
}

function validateContent(content: string, maxChars: number, t: Translate): string | null {
  const text = content.trim();
  if (!text) return t('rules.editor.contentRequired');
  if (text.length > maxChars) {
    return t('rules.editor.tooLong').replace('{max}', String(maxChars));
  }
  return null;
}

interface UseRuleSubmitInput extends RuleEditorFormInput {
  fields: EditorFields;
  expectedUpdatedAtOverride: number | undefined;
  refreshConflict: (target: RuleEntry) => Promise<void>;
  setError: (message: string | null) => void;
}

function useRuleSubmit(input: UseRuleSubmitInput) {
  const { isOpen, projectId, entry, fields, maxChars, t, onSaved, onClose, setError } = input;
  const { expectedUpdatedAtOverride, refreshConflict } = input;
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setSaving(false);
    setError(null);
  }, [isOpen, entry, setError]);

  const handleSaveError = async (err: unknown) => {
    setError(t('rules.action.saveFailed').replace('{message}', errorMessage(err)));
    if (isConflictError(err) && entry) await refreshConflict(entry);
  };

  const handleSave = async () => {
    const validation = validateContent(fields.content, maxChars, t);
    if (validation) {
      setError(validation);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await persistRule({
        projectId,
        entry,
        layer: fields.layer,
        category: fields.category,
        content: fields.content.trim(),
        trigger: fields.trigger,
        priority: fields.priority,
        enabled: fields.enabled,
        expectedUpdatedAt: expectedUpdatedAtOverride,
      });
      await onSaved();
      onClose();
    } catch (err) {
      await handleSaveError(err);
    } finally {
      setSaving(false);
    }
  };

  return { saving, handleSave };
}

export function useRuleEditorForm(input: RuleEditorFormInput): RuleEditorFormState {
  const { isOpen, entry, initialLayer, projectId, t } = input;
  const [error, setError] = useState<string | null>(null);
  const fields = useEditorFields({ isOpen, entry, initialLayer, t });

  useEffect(() => {
    if (isOpen) setError(null);
  }, [isOpen, entry]);

  const raw = useRawPreview({ isOpen, projectId, layer: fields.layer, t, setError });
  const conflict = useConflictRecovery({
    isOpen,
    projectId,
    entry,
    fields,
    clearError: () => setError(null),
  });
  const submit = useRuleSubmit({
    ...input,
    fields,
    expectedUpdatedAtOverride: conflict.expectedUpdatedAtOverride,
    refreshConflict: conflict.refreshConflict,
    setError,
  });
  const tooLong = fields.content.length > input.maxChars;
  const canSave = Boolean(fields.content.trim()) && !tooLong;

  return {
    ...fields,
    isEdit: Boolean(entry),
    saving: submit.saving,
    error,
    conflictCurrent: conflict.conflictCurrent,
    rawPreview: raw.rawPreview,
    rawLoading: raw.rawLoading,
    tooLong,
    canSave,
    handleSave: submit.handleSave,
    handleToggleRaw: raw.handleToggleRaw,
    handleUseServer: conflict.handleUseServer,
  };
}
