// src/features/rules/RuleEditorBody.tsx
/** RuleEditorDialog 的表单主体与冲突/错误区域；仅负责渲染。 */
import type { RuleEntry } from '../../shared/api/rulesApi';

import {
  CategoryField,
  ConflictNotice,
  ConstraintFields,
  ContentField,
  LayerField,
  RawPreviewSection,
} from './RuleEditorFields';
import type { RuleEditorFormState } from './useRuleEditorForm';

interface RuleEditorFeedbackProps {
  conflictCurrent: RuleEntry | null;
  error: string | null;
  onUseServer: () => void;
}

function RuleEditorFeedback({ conflictCurrent, error, onUseServer }: RuleEditorFeedbackProps) {
  return (
    <>
      {conflictCurrent && (
        <ConflictNotice
          current={conflictCurrent}
          layer={conflictCurrent.layer}
          onUseServer={onUseServer}
        />
      )}
      {error && (
        <p className="text-xs text-destructive" data-testid="rule-editor-error">
          {error}
        </p>
      )}
    </>
  );
}

interface RuleEditorBodyProps {
  form: RuleEditorFormState;
  maxChars: number;
}

export function RuleEditorBody({ form, maxChars }: RuleEditorBodyProps) {
  return (
    <>
      {!form.isEdit && <LayerField layer={form.layer} onChange={form.handleLayerChange} />}
      {(form.layer === 'constraint' || !form.isEdit) && (
        <CategoryField layer={form.layer} category={form.category} onChange={form.setCategory} />
      )}
      <ContentField
        content={form.content}
        maxChars={maxChars}
        tooLong={form.tooLong}
        onChange={form.setContent}
      />
      {form.layer === 'constraint' && (
        <ConstraintFields
          trigger={form.trigger}
          priority={form.priority}
          enabled={form.enabled}
          onTriggerChange={form.setTrigger}
          onPriorityChange={form.setPriority}
          onEnabledChange={form.setEnabled}
        />
      )}
      {form.layer !== 'constraint' && (
        <RawPreviewSection
          rawPreview={form.rawPreview}
          rawLoading={form.rawLoading}
          onToggle={() => void form.handleToggleRaw()}
        />
      )}
      <RuleEditorFeedback
        conflictCurrent={form.conflictCurrent}
        error={form.error}
        onUseServer={form.handleUseServer}
      />
    </>
  );
}
