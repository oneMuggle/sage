// src/features/rules/RuleEditorFields.tsx
/**
 * Presentational fields for {@link RuleEditorDialog}. Split out so each
 * component stays small; all state and API calls live in RuleEditorDialog.
 */
import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, type ReactNode } from 'react';

import type {
  CreatableRuleLayer,
  RawRulesResponse,
  RuleEntry,
  RuleLayer,
} from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { NumberField } from '../../shared/ui/NumberField';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select/Select';
import { Switch } from '../../shared/ui/Switch/Switch';
import { Textarea } from '../../shared/ui/Textarea';

interface ShellProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer: ReactNode;
}

function DialogBackdrop() {
  return (
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
  );
}

function DialogHeader({ title, onClose }: { title: string; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-between border-b border-border px-5 py-3">
      <Dialog.Title as="h3" className="text-sm font-semibold text-foreground">
        {title}
      </Dialog.Title>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label={t('rules.action.close')}
        data-testid="rule-editor-cancel-icon"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

interface DialogFrameProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}

function DialogFrame({ title, onClose, children, footer }: DialogFrameProps) {
  return (
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
        data-testid="rule-editor"
      >
        <DialogHeader title={title} onClose={onClose} />
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">{children}</div>
        {footer}
      </Dialog.Panel>
    </Transition.Child>
  );
}

export function RuleEditorShell({ isOpen, onClose, title, children, footer }: ShellProps) {
  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <DialogBackdrop />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <DialogFrame title={title} onClose={onClose} footer={footer}>
            {children}
          </DialogFrame>
        </div>
      </Dialog>
    </Transition>
  );
}

export function LayerField({
  layer,
  onChange,
}: {
  layer: CreatableRuleLayer;
  onChange: (next: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium text-foreground">{t('rules.editor.layer')}</span>
      <Select value={layer} onValueChange={onChange}>
        <SelectTrigger
          aria-label={t('rules.editor.layer')}
          className="w-full"
          data-testid="rule-editor-layer"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="constraint">{t('rules.layer.constraint')}</SelectItem>
          <SelectItem value="doc">{t('rules.layer.doc')}</SelectItem>
          <SelectItem value="global">{t('rules.layer.global')}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

export function CategoryField({
  layer,
  category,
  onChange,
}: {
  layer: CreatableRuleLayer;
  category: string;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  const isConstraint = layer === 'constraint';
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-foreground">
        {isConstraint ? t('rules.editor.category') : t('rules.editor.sectionHeading')}
      </span>
      <Input
        value={category}
        onChange={(event) => onChange(event.target.value)}
        data-testid="rule-editor-category"
      />
      {!isConstraint && (
        <span className="block text-ui-2xs text-muted-foreground">
          {t('rules.editor.sectionHint')}
        </span>
      )}
    </label>
  );
}

export function ContentField({
  content,
  maxChars,
  tooLong,
  onChange,
}: {
  content: string;
  maxChars: number;
  tooLong: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  return (
    <label className="block space-y-1">
      <span className="flex items-center justify-between text-xs font-medium text-foreground">
        {t('rules.editor.content')}
        <span
          className={tooLong ? 'text-destructive' : 'text-muted-foreground'}
          data-testid="rule-editor-counter"
        >
          {content.length}/{maxChars}
        </span>
      </span>
      <Textarea
        value={content}
        rows={6}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t('rules.editor.contentPlaceholder')}
        data-testid="rule-editor-content"
      />
    </label>
  );
}

export function ConstraintFields({
  trigger,
  priority,
  enabled,
  onTriggerChange,
  onPriorityChange,
  onEnabledChange,
}: {
  trigger: string;
  priority: number;
  enabled: boolean;
  onTriggerChange: (value: string) => void;
  onPriorityChange: (value: number) => void;
  onEnabledChange: (value: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <>
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-[14rem] flex-1 space-y-1">
          <span className="text-xs font-medium text-foreground">{t('rules.editor.trigger')}</span>
          <Input
            value={trigger}
            onChange={(event) => onTriggerChange(event.target.value)}
            placeholder={t('rules.editor.triggerHint')}
            data-testid="rule-editor-trigger"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-xs font-medium text-foreground">
            {t('rules.editor.priority')}
          </span>
          <NumberField
            value={priority}
            onChange={onPriorityChange}
            min={1}
            max={9}
            testId="rule-editor-priority"
          />
        </label>
      </div>
      <label
        htmlFor="rule-editor-enabled"
        className="flex items-center gap-2 text-xs text-foreground"
      >
        <Switch
          id="rule-editor-enabled"
          checked={enabled}
          onCheckedChange={onEnabledChange}
          data-testid="rule-editor-enabled"
        />
        {t('rules.editor.enabled')}
      </label>
    </>
  );
}

export function RawPreviewSection({
  rawPreview,
  rawLoading,
  onToggle,
}: {
  rawPreview: RawRulesResponse | null;
  rawLoading: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <Button
        variant="secondary"
        size="sm"
        onClick={onToggle}
        disabled={rawLoading}
        data-testid="rule-editor-raw-open"
      >
        {rawPreview ? t('rules.editor.rawHide') : t('rules.editor.rawOpen')}
      </Button>
      {rawLoading && (
        <p className="text-ui-2xs text-muted-foreground">{t('rules.editor.rawLoading')}</p>
      )}
      {rawPreview && (
        <div className="space-y-1" data-testid="rule-editor-raw">
          <p className="text-ui-2xs text-muted-foreground">
            {t('rules.editor.rawPath').replace('{path}', rawPreview.path)}
          </p>
          <pre className="max-h-48 overflow-auto rounded-lg border border-border bg-muted/40 p-2 text-ui-2xs text-foreground">
            {rawPreview.content}
          </pre>
          {rawPreview.truncated && (
            <p className="text-ui-2xs text-amber-600">{t('rules.editor.rawTruncated')}</p>
          )}
        </div>
      )}
    </div>
  );
}

export function EditorFooter({
  saving,
  canSave,
  onCancel,
  onSave,
}: {
  saving: boolean;
  canSave: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
      <Button
        variant="ghost"
        size="sm"
        onClick={onCancel}
        disabled={saving}
        data-testid="rule-editor-cancel"
      >
        {t('rules.editor.cancel')}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={onSave}
        disabled={saving || !canSave}
        data-testid="rule-editor-save"
      >
        {saving ? t('rules.editor.saving') : t('rules.editor.save')}
      </Button>
    </div>
  );
}

interface ConflictNoticeProps {
  current: RuleEntry;
  /** 冲突规则所属层；非约束层只展示分类与正文。 */
  layer: RuleLayer;
  onUseServer: () => void;
}

/** 409 时展示服务器上的当前版本，允许一键以其为准。 */
export function ConflictNotice({ current, layer, onUseServer }: ConflictNoticeProps) {
  const { t } = useI18n();
  const rows: Array<[string, string]> = [
    [t('rules.editor.category'), current.category],
    [t('rules.editor.content'), current.content],
  ];
  if (layer === 'constraint') {
    rows.push([t('rules.editor.trigger'), current.trigger || '—']);
    rows.push([t('rules.editor.priority'), String(current.priority)]);
    rows.push([
      t('rules.editor.enabled'),
      current.enabled ? t('rules.row.enabled') : t('rules.row.disabled'),
    ]);
  }
  return (
    <div
      className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2"
      data-testid="rule-editor-conflict"
    >
      <p className="text-xs font-medium text-foreground">{t('rules.conflict.title')}</p>
      <p className="text-ui-2xs text-muted-foreground">{t('rules.conflict.hint')}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-ui-2xs">
        {rows.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="whitespace-pre-wrap text-foreground">{value}</dd>
          </Fragment>
        ))}
      </dl>
      <Button
        variant="secondary"
        size="sm"
        onClick={onUseServer}
        data-testid="rule-editor-use-server"
      >
        {t('rules.conflict.useServer')}
      </Button>
    </div>
  );
}
