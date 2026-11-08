// src/features/rules/RuleEditorDialog.tsx
import type { CreatableRuleLayer, RuleEntry } from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';

import { RuleEditorBody } from './RuleEditorBody';
import { EditorFooter } from './RuleEditorFields';
import { RuleEditorShell } from './RuleEditorShell';
import { useRuleEditorForm } from './useRuleEditorForm';

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

export function RuleEditorDialog({
  isOpen,
  onClose,
  projectId,
  entry = null,
  initialLayer = 'constraint',
  onSaved,
}: RuleEditorDialogProps) {
  const { t } = useI18n();
  const form = useRuleEditorForm({
    isOpen,
    projectId,
    entry,
    initialLayer,
    maxChars: MAX_RULE_CHARS,
    onSaved,
    onClose,
    t,
  });

  return (
    <RuleEditorShell
      isOpen={isOpen}
      onClose={onClose}
      title={form.isEdit ? t('rules.editor.titleEdit') : t('rules.editor.titleCreate')}
      footer={
        <EditorFooter
          saving={form.saving}
          canSave={form.canSave}
          onCancel={onClose}
          onSave={() => void form.handleSave()}
        />
      }
    >
      <RuleEditorBody form={form} maxChars={MAX_RULE_CHARS} />
    </RuleEditorShell>
  );
}
