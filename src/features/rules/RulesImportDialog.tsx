import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';

import { rulesApi, type ImportCandidate } from '../../shared/api/rulesApi';
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

export interface RulesImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onApplied?: () => void;
}

type Stage = 'idle' | 'loading' | 'ready' | 'applying';

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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Read a picked file; some jsdom builds lack File.text, so fall back to Response. */
async function readFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Response(file).text();
}

function isActionable(candidate: ImportCandidate): boolean {
  return candidate.kind !== 'playbook';
}

function isSelectableByDefault(candidate: ImportCandidate): boolean {
  return isActionable(candidate) && (candidate.status === 'new' || candidate.status === 'conflict');
}

export function RulesImportDialog({
  open,
  onOpenChange,
  projectId,
  onApplied,
}: RulesImportDialogProps) {
  const { t } = useI18n();
  const [stage, setStage] = useState<Stage>('idle');
  const [candidates, setCandidates] = useState<ImportCandidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [overwrite, setOverwrite] = useState(false);
  const [globalAck, setGlobalAck] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const envelopeRef = useRef<unknown>(null);

  const actionableCandidates = candidates.filter(isActionable);
  const hasGlobal = actionableCandidates.some((candidate) => candidate.kind === 'global');
  const hasPlaybook = candidates.some((candidate) => candidate.kind === 'playbook');

  const handleFile = useCallback(
    async (file: File) => {
      setStage('loading');
      setParseError(null);
      try {
        const text = await readFileText(file);
        const envelope = JSON.parse(text);
        envelopeRef.current = envelope;
        const { candidates: list } = await rulesApi.previewImport(envelope, projectId);
        setCandidates(list);
        setSelectedIds(new Set(list.filter(isSelectableByDefault).map((item) => item.id)));
        setStage('ready');
      } catch (error) {
        setParseError(errorMessage(error));
        setStage('idle');
      }
    },
    [projectId],
  );

  const handleApply = useCallback(async () => {
    if (!envelopeRef.current || stage !== 'ready' || !projectId) return;
    if (hasGlobal && !globalAck) return;
    const selected = candidates
      .filter((candidate) => isActionable(candidate) && selectedIds.has(candidate.id))
      .map((candidate) => candidate.id);
    if (selected.length === 0) return;
    setStage('applying');
    try {
      const result = await rulesApi.applyImport(
        envelopeRef.current,
        projectId,
        selected,
        overwrite,
      );
      toast.success(t('rules.import.applied').replace('{applied}', String(result.applied)));
      onApplied?.();
      onOpenChange(false);
    } catch (error) {
      toast.error(t('rules.import.apply_failed').replace('{message}', errorMessage(error)));
    } finally {
      setStage('ready');
    }
  }, [
    stage,
    projectId,
    hasGlobal,
    globalAck,
    candidates,
    selectedIds,
    overwrite,
    t,
    onApplied,
    onOpenChange,
  ]);

  const toggle = useCallback((id: string, next: boolean) => {
    setSelectedIds((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(id);
      else copy.delete(id);
      return copy;
    });
  }, []);

  const selectAllNew = useCallback(() => {
    setSelectedIds(new Set(actionableCandidates.filter(isSelectableByDefault).map((c) => c.id)));
  }, [actionableCandidates]);

  const applyDisabled =
    stage !== 'ready' || !projectId || selectedIds.size === 0 || (hasGlobal && !globalAck);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('rules.import.title')}</DialogTitle>
          <DialogDescription>{t('rules.import.upload_hint')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".sagerules.json,application/json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) void handleFile(file);
            }}
            data-testid="rules-import-file"
          />

          {!projectId ? (
            <p role="alert" className="text-sm text-warning">
              {t('rules.import.no_project')}
            </p>
          ) : null}

          {stage === 'idle' ? (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
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

          {stage === 'loading' ? (
            <p className="text-sm text-text-secondary">{t('rules.import.parsing')}</p>
          ) : null}

          {(stage === 'ready' || stage === 'applying') && actionableCandidates.length === 0 ? (
            <p className="text-sm text-text-secondary">{t('rules.import.no_candidates')}</p>
          ) : null}

          {(stage === 'ready' || stage === 'applying') && actionableCandidates.length > 0 ? (
            <>
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={selectAllNew}
                  className="text-xs text-primary hover:underline"
                  data-testid="rules-import-select-new"
                >
                  {t('rules.import.select_all_new')}
                </button>
                <label className="flex items-center gap-2 text-xs">
                  <Checkbox
                    checked={overwrite}
                    onCheckedChange={(next) => setOverwrite(Boolean(next))}
                    data-testid="rules-import-overwrite"
                  />
                  <span>{t('rules.import.overwrite_hint')}</span>
                </label>
              </div>

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
                          <span className="text-xs text-text-tertiary">
                            {candidate.category}
                          </span>
                        ) : null}
                      </div>
                      <p className="line-clamp-2 text-text">{candidate.content}</p>
                    </div>
                  </li>
                ))}
              </ul>

              {hasPlaybook ? (
                <p
                  className="text-xs text-text-tertiary"
                  data-testid="rules-import-playbook-deferred"
                >
                  {t('rules.import.deferred_playbook')}
                </p>
              ) : null}

              {hasGlobal ? (
                <label
                  className="flex items-start gap-2 rounded border border-warning/50 bg-warning/10 p-2 text-xs text-warning"
                  data-testid="rules-import-global-ack"
                >
                  <Checkbox
                    checked={globalAck}
                    onCheckedChange={(next) => setGlobalAck(Boolean(next))}
                  />
                  <span>{t('rules.import.global_ack')}</span>
                </label>
              ) : null}
            </>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={stage === 'applying'}
          >
            {t('rules.editor.cancel')}
          </Button>
          <Button onClick={handleApply} disabled={applyDisabled} data-testid="rules-import-apply">
            {stage === 'applying' ? t('rules.import.applying') : t('rules.import.apply')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
