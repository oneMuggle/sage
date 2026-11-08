import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';

import { rulesApi, type ImportCandidate } from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

type Stage = 'idle' | 'loading' | 'ready' | 'applying';

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

export interface RulesImportHookResult {
  stage: Stage;
  candidates: ImportCandidate[];
  selectedIds: Set<string>;
  overwrite: boolean;
  setOverwrite: (v: boolean) => void;
  globalAck: boolean;
  setGlobalAck: (v: boolean) => void;
  parseError: string | null;
  fileInputRef: React.RefObject<HTMLInputElement>;
  actionableCandidates: ImportCandidate[];
  hasGlobal: boolean;
  hasPlaybook: boolean;
  handleFile: (file: File) => Promise<void>;
  handleApply: () => Promise<void>;
  toggle: (id: string, next: boolean) => void;
  selectAllNew: () => void;
  applyDisabled: boolean;
}

export function useRulesImport(
  projectId: string,
  onApplied?: () => void,
  onOpenChange?: (open: boolean) => void,
): RulesImportHookResult {
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

  const handleFile = useFileHandler(projectId, setStage, setParseError, setCandidates, setSelectedIds, envelopeRef);
  const handleApply = useApplyHandler(
    stage, projectId, hasGlobal, globalAck, candidates, selectedIds, overwrite, t, onApplied, onOpenChange, envelopeRef, setStage,
  );
  const toggle = useToggle(setSelectedIds);
  const selectAllNew = useSelectAllNew(actionableCandidates, setSelectedIds);

  const applyDisabled =
    stage !== 'ready' || !projectId || selectedIds.size === 0 || (hasGlobal && !globalAck);

  return {
    stage,
    candidates,
    selectedIds,
    overwrite,
    setOverwrite,
    globalAck,
    setGlobalAck,
    parseError,
    fileInputRef,
    actionableCandidates,
    hasGlobal,
    hasPlaybook,
    handleFile,
    handleApply,
    toggle,
    selectAllNew,
    applyDisabled,
  };
}

function useFileHandler(
  projectId: string,
  setStage: (v: Stage) => void,
  setParseError: (v: string | null) => void,
  setCandidates: (v: ImportCandidate[]) => void,
  setSelectedIds: (v: Set<string>) => void,
  envelopeRef: React.MutableRefObject<unknown>,
) {
  return useCallback(
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
    [projectId, setStage, setParseError, setCandidates, setSelectedIds, envelopeRef],
  );
}

function useApplyHandler(
  stage: Stage,
  projectId: string,
  hasGlobal: boolean,
  globalAck: boolean,
  candidates: ImportCandidate[],
  selectedIds: Set<string>,
  overwrite: boolean,
  t: (key: TranslationKey) => string,
  onApplied?: () => void,
  onOpenChange?: (open: boolean) => void,
  envelopeRef?: React.MutableRefObject<unknown>,
  setStage?: (v: Stage) => void,
) {
  return useCallback(async () => {
    if (!envelopeRef?.current || stage !== 'ready' || !projectId) return;
    if (hasGlobal && !globalAck) return;
    const selected = candidates
      .filter((candidate) => isActionable(candidate) && selectedIds.has(candidate.id))
      .map((candidate) => candidate.id);
    if (selected.length === 0) return;
    setStage?.('applying');
    try {
      const result = await rulesApi.applyImport(envelopeRef.current, projectId, selected, overwrite);
      toast.success(t('rules.import.applied').replace('{applied}', String(result.applied)));
      onApplied?.();
      onOpenChange?.(false);
    } catch (error) {
      toast.error(t('rules.import.apply_failed').replace('{message}', errorMessage(error)));
    } finally {
      setStage?.('ready');
    }
  }, [stage, projectId, hasGlobal, globalAck, candidates, selectedIds, overwrite, t, onApplied, onOpenChange, envelopeRef, setStage]);
}

function useToggle(setSelectedIds: React.Dispatch<React.SetStateAction<Set<string>>>) {
  return useCallback((id: string, next: boolean) => {
    setSelectedIds((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(id);
      else copy.delete(id);
      return copy;
    });
  }, [setSelectedIds]);
}

function useSelectAllNew(
  actionableCandidates: ImportCandidate[],
  setSelectedIds: React.Dispatch<React.SetStateAction<Set<string>>>,
) {
  return useCallback(() => {
    setSelectedIds(new Set(actionableCandidates.filter(isSelectableByDefault).map((c) => c.id)));
  }, [actionableCandidates, setSelectedIds]);
}
