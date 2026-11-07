// src/features/rules/RuleEditorDialog.tsx
import { useEffect, useState } from 'react';

import {
  rulesApi,
  type CreatableRuleLayer,
  type RawRulesResponse,
  type RuleEntry,
} from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';

import {
  CategoryField,
  ConstraintFields,
  ContentField,
  EditorFooter,
  LayerField,
  RawPreviewSection,
  RuleEditorShell,
} from './RuleEditorFields';

/** 与后端 `markdown_rules.MAX_RULE_CHARS` 保持一致。 */
export const MAX_RULE_CHARS = 2000;

export interface RuleEditorDialogProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  /** 传入即为编辑；`null`/`undefined` 为新建。 */
  entry?: RuleEntry | null;
  /** 新建时的默认层。 */
  initialLayer?: CreatableRuleLayer;
  onSaved: () => void | Promise<void>;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
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
      expectedUpdatedAt: entry.updatedAt,
    });
    return;
  }
  await rulesApi.update(projectId, { layer, ruleId: entry.id, patch: { content } });
}

export function RuleEditorDialog({
  isOpen,
  onClose,
  projectId,
  entry = null,
  initialLayer = 'constraint',
  onSaved,
}: RuleEditorDialogProps) {
  const { t } = useI18n();
  const isEdit = Boolean(entry);
  const [layer, setLayer] = useState<CreatableRuleLayer>(initialLayer);
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [trigger, setTrigger] = useState('');
  const [priority, setPriority] = useState(5);
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rawPreview, setRawPreview] = useState<RawRulesResponse | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  const defaultCategory = (next: CreatableRuleLayer): string =>
    next === 'constraint' ? t('rules.editor.defaultCategory') : t('rules.editor.defaultSection');

  useEffect(() => {
    if (!isOpen) return;
    const nextLayer: CreatableRuleLayer =
      entry && entry.layer !== 'playbook' ? entry.layer : initialLayer;
    setLayer(nextLayer);
    setCategory(entry?.category ?? defaultCategory(nextLayer));
    setContent(entry?.content ?? '');
    setTrigger(entry?.trigger ?? '');
    setPriority(entry?.priority ?? 5);
    setEnabled(entry?.enabled ?? true);
    setSaving(false);
    setError(null);
    setRawPreview(null);
    setRawLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在打开/切换目标时重置
  }, [isOpen, entry, initialLayer]);

  const tooLong = content.length > MAX_RULE_CHARS;
  const canSave = Boolean(content.trim()) && !tooLong;

  const handleLayerChange = (next: string) => {
    const nextLayer = next as CreatableRuleLayer;
    setLayer(nextLayer);
    if (!isEdit) setCategory(defaultCategory(nextLayer));
  };

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

  const handleSave = async () => {
    const text = content.trim();
    if (!text) {
      setError(t('rules.editor.contentRequired'));
      return;
    }
    if (text.length > MAX_RULE_CHARS) {
      setError(t('rules.editor.tooLong').replace('{max}', String(MAX_RULE_CHARS)));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await persistRule({
        projectId,
        entry,
        layer,
        category,
        content: text,
        trigger,
        priority,
        enabled,
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <RuleEditorShell
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? t('rules.editor.titleEdit') : t('rules.editor.titleCreate')}
      footer={
        <EditorFooter
          saving={saving}
          canSave={canSave}
          onCancel={onClose}
          onSave={() => void handleSave()}
        />
      }
    >
      {!isEdit && <LayerField layer={layer} onChange={handleLayerChange} />}
      {(layer === 'constraint' || !isEdit) && (
        <CategoryField layer={layer} category={category} onChange={setCategory} />
      )}
      <ContentField
        content={content}
        maxChars={MAX_RULE_CHARS}
        tooLong={tooLong}
        onChange={setContent}
      />
      {layer === 'constraint' && (
        <ConstraintFields
          trigger={trigger}
          priority={priority}
          enabled={enabled}
          onTriggerChange={setTrigger}
          onPriorityChange={setPriority}
          onEnabledChange={setEnabled}
        />
      )}
      {layer !== 'constraint' && (
        <RawPreviewSection
          rawPreview={rawPreview}
          rawLoading={rawLoading}
          onToggle={() => void handleToggleRaw()}
        />
      )}
      {error && (
        <p className="text-xs text-destructive" data-testid="rule-editor-error">
          {error}
        </p>
      )}
    </RuleEditorShell>
  );
}
