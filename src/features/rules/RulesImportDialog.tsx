import type { ImportCandidate } from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Checkbox } from '../../shared/ui/Checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

import { useRulesImport, type RulesImportHookResult } from './useRulesImport';

export interface RulesImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onApplied?: () => void;
}

const LAYER_LABEL_KEY: Record<ImportCandidate['kind'], TranslationKey> = {
  constraint: 'rules.import.layer.constraint',
  doc: 'rules.import.layer.doc',
  global: 'rules.import.layer.global',
  playbook: 'rules.import.layer.playbook',
};

const STATUS_LABEL_KEY: Record<ImportCandidate['status'], TranslationKey> = {
  new: 'rules.import.status.new',
  duplicate: 'rules.import.status.duplicate',
  conflict: 'rules.import.status.conflict',
};

const STATUS_STYLE: Record<ImportCandidate['status'], string> = {
  new: 'text-success',
  duplicate: 'text-text-tertiary',
  conflict: 'text-warning',
};

function ImportHeader({
  stage,
  parseError,
  fileInputRef,
  onFile,
  onPick,
}: {
  stage: string;
  parseError: string | null;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onFile: (file: File) => void;
  onPick: () => void;
}) {
  const { t } = useI18n();
  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".sagerules.json,application/json"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) onFile(file);
        }}
        data-testid="rules-import-file"
      />
      {stage === 'idle' ? (
        <button
          type="button"
          onClick={onPick}
          className="w-full rounded border border-dashed border-border p-6 text-sm text-text-secondary hover:border-primary hover:text-primary"
          data-testid="rules-import-picker"
        >
          {t('rules.import.upload_hint')}
        </button>
      ) : null}
      {parseError ? (
        <p role="alert" className="text-sm text-error">
          {t('rules.import.parse_failed').replace('{message}', parseError)}
        </p>
      ) : null}
    </>
  );
}

function CandidateList({
  actionableCandidates,
  selectedIds,
  toggle,
}: {
  actionableCandidates: ImportCandidate[];
  selectedIds: Set<string>;
  toggle: (id: string, next: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <ul
      className="max-h-80 divide-y divide-border overflow-y-auto rounded border border-border"
      data-testid="rules-import-candidates"
    >
      {actionableCandidates.map((candidate) => (
        <li
          key={candidate.id}
          className="flex items-start gap-3 p-2 text-sm"
          data-testid={`rules-import-candidate-${candidate.id}`}
        >
          <Checkbox
            checked={selectedIds.has(candidate.id)}
            onCheckedChange={(next) => toggle(candidate.id, Boolean(next))}
            disabled={candidate.status === 'duplicate'}
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-tertiary">
                {t(LAYER_LABEL_KEY[candidate.kind])}
              </span>
              <span className={STATUS_STYLE[candidate.status]}>
                {t(STATUS_LABEL_KEY[candidate.status])}
              </span>
              {candidate.category ? (
                <span className="text-xs text-text-tertiary">{candidate.category}</span>
              ) : null}
            </div>
            <p className="line-clamp-2 text-text">{candidate.content}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SelectionBar({ hook }: { hook: RulesImportHookResult }) {
  const { t } = useI18n();
  return (
    <>
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={hook.selectAllNew}
          className="text-xs text-primary hover:underline"
          data-testid="rules-import-select-new"
        >
          {t('rules.import.select_all_new')}
        </button>
        <label className="flex items-center gap-2 text-xs">
          <Checkbox
            checked={hook.overwrite}
            onCheckedChange={(next) => hook.setOverwrite(Boolean(next))}
            data-testid="rules-import-overwrite"
          />
          <span>{t('rules.import.overwrite_hint')}</span>
        </label>
      </div>
      <CandidateList
        actionableCandidates={hook.actionableCandidates}
        selectedIds={hook.selectedIds}
        toggle={hook.toggle}
      />
      {hook.hasPlaybook ? (
        <p className="text-xs text-text-tertiary" data-testid="rules-import-playbook-deferred">
          {t('rules.import.deferred_playbook')}
        </p>
      ) : null}
      {hook.hasGlobal ? (
        <label
          className="flex items-start gap-2 rounded border border-warning/50 bg-warning/10 p-2 text-xs text-warning"
          data-testid="rules-import-global-ack"
        >
          <Checkbox
            checked={hook.globalAck}
            onCheckedChange={(next) => hook.setGlobalAck(Boolean(next))}
          />
          <span>{t('rules.import.global_ack')}</span>
        </label>
      ) : null}
    </>
  );
}

function ImportBody({ hook, projectId }: { hook: RulesImportHookResult; projectId: string }) {
  const { t } = useI18n();
  return (
    <div className="space-y-3 py-2">
      {!projectId ? (
        <p role="alert" className="text-sm text-warning">
          {t('rules.import.no_project')}
        </p>
      ) : null}
      <ImportHeader
        stage={hook.stage}
        parseError={hook.parseError}
        fileInputRef={hook.fileInputRef}
        onFile={(file) => void hook.handleFile(file)}
        onPick={() => hook.fileInputRef.current?.click()}
      />
      {hook.stage === 'loading' ? (
        <p className="text-sm text-text-secondary">{t('rules.import.parsing')}</p>
      ) : null}
      {(hook.stage === 'ready' || hook.stage === 'applying') &&
      hook.actionableCandidates.length === 0 ? (
        <p className="text-sm text-text-secondary">{t('rules.import.no_candidates')}</p>
      ) : null}
      {(hook.stage === 'ready' || hook.stage === 'applying') &&
      hook.actionableCandidates.length > 0 ? (
        <SelectionBar hook={hook} />
      ) : null}
    </div>
  );
}

export function RulesImportDialog({
  open,
  onOpenChange,
  projectId,
  onApplied,
}: RulesImportDialogProps) {
  const { t } = useI18n();
  const hook = useRulesImport(projectId, onApplied, onOpenChange);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('rules.import.title')}</DialogTitle>
          <DialogDescription>{t('rules.import.upload_hint')}</DialogDescription>
        </DialogHeader>
        <ImportBody hook={hook} projectId={projectId} />
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={hook.stage === 'applying'}
          >
            {t('rules.editor.cancel')}
          </Button>
          <Button
            onClick={hook.handleApply}
            disabled={hook.applyDisabled}
            data-testid="rules-import-apply"
          >
            {hook.stage === 'applying' ? t('rules.import.applying') : t('rules.import.apply')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
