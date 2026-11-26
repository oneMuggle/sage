/**
 * RulesSubtabs — the rules tab's second-level navigation.
 *
 * Part of the 2026-11 IA redesign. Before this, `renderRulesTab()` in
 * `Office.tsx` stacked six panels vertically (rule CRUD / spec library /
 * AI assistant / rule extraction / bulk audit / guide card). The result read
 * as one undifferentiated wall: three competing "audit" entry points and
 * four separate file pickers.
 *
 * This component splits that wall into three single-concept sub-tabs:
 *
 *   1. `rules-library` — rule groups + CRUD + rule-pack import/export, plus
 *      a "extract rules from the current document" shortcut in the top bar
 *      and the external spec library in a collapsed drawer.
 *   2. `ai-audit`      — audit / rewrite the document you are looking at.
 *   3. `batch-tools`   — bulk audit across many files.
 *
 * Each sub-tab owns exactly one audit entry point, so the previous overlap
 * is gone: rule-group audit lives in the library, semantic AI audit lives in
 * the AI tab, bulk audit lives in the batch tab.
 *
 * The extract shortcut replaces the old `WordRuleExtractionPanel`: it acts on
 * the already-open document (no second file picker), writes the result into
 * a fresh rule group, and reports the count via a toast.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import { officeRulesApi } from '../../../shared/api/officeRulesApi';
import { useKeepAliveTabs } from '../../../shared/lib/hooks/useKeepAliveTabs';
import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../shared/ui/Tabs';
import { OfficeSpecLibrary } from '../OfficeSpecLibrary';
import { officeDocumentPath } from '../officeDocumentPath';

import { AiAuditTab } from './AiAuditTab';
import { BatchToolsTab } from './BatchToolsTab';
import { RuleExtractionDraft } from './RuleExtractionDraft';
import { RulesWorkspace } from './RulesWorkspace';
import { useRuleDraftStore } from './ruleDraftStore';

const RULE_SUBTAB_IDS = ['rules-library', 'ai-audit', 'batch-tools'] as const;
type RuleSubtabId = (typeof RULE_SUBTAB_IDS)[number];

const RULE_SUBTAB_LABEL_KEYS: Record<RuleSubtabId, TranslationKey> = {
  'rules-library': 'office.rules.subtabs.rulesLibrary',
  'ai-audit': 'office.rules.subtabs.aiAudit',
  'batch-tools': 'office.rules.subtabs.batchTools',
};

export interface RulesSubtabsProps {
  workspacePath: string;
  /** Jump back to the documents tab (used by the batch-tools guide card). */
  onGoToDocuments: () => void;
}

export function RulesSubtabs({ workspacePath, onGoToDocuments }: RulesSubtabsProps) {
  const { t } = useI18n();
  const activeDocument = useOfficeWorkspaceStore((state) => state.activeDocument);
  const [activeSubtab, setActiveSubtab] = useState<RuleSubtabId>('rules-library');
  const [extracting, setExtracting] = useState(false);
  // Bumping `reloadKey` makes the rule workspace refetch its group list;
  // `focusGroupId` selects the group that extraction just created.
  const [reloadKey, setReloadKey] = useState(0);
  const [focusGroupId, setFocusGroupId] = useState<string | null>(null);
  const mounted = useKeepAliveTabs(activeSubtab);

  const openDraft = useRuleDraftStore((state) => state.open);
  const resumeDraft = useRuleDraftStore((state) => state.resume);
  const resetDraft = useRuleDraftStore((state) => state.reset);
  const setLoading = useRuleDraftStore((state) => state.setLoading);
  const setDraft = useRuleDraftStore((state) => state.setDraft);
  const setDraftError = useRuleDraftStore((state) => state.setError);
  const draftRuleCount = useRuleDraftStore((state) => state.rules.length);
  const isDraftOpen = useRuleDraftStore((state) => state.isOpen);
  const draftSourceName = useRuleDraftStore((state) => state.sourceName);

  const documentPath = activeDocument ? officeDocumentPath(activeDocument) : null;

  const handleExtractFromActiveDocument = async () => {
    if (!activeDocument || !documentPath) {
      toast.warning(t('office.rules.extractNoActiveDoc'));
      return;
    }
    const sourceName =
      activeDocument.original_filename ?? activeDocument.generated_filename ?? activeDocument.id;
    openDraft(sourceName, workspacePath);
    setLoading(true);
    setExtracting(true);
    try {
      const result = await officeRulesApi.extractDraft({
        workspace_path: workspacePath,
        file_path: documentPath,
        file_type: 'template',
        use_llm: true,
      });
      setDraft(
        result.rules,
        result.conflicts,
        result.warnings.map((w) => w.message),
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setDraftError(message);
    } finally {
      setExtracting(false);
    }
  };

  const handleCommitted = (groupId: string, _count: number) => {
    setFocusGroupId(groupId);
    setReloadKey((key) => key + 1);
  };

  return (
    <div className="space-y-4">
      <Tabs value={activeSubtab} onValueChange={(value) => setActiveSubtab(value as RuleSubtabId)}>
        <TabsList aria-label={t('office.rules.subtabs.label')} data-testid="office-rules-subtabs">
          {RULE_SUBTAB_IDS.map((id) => (
            <TabsTrigger key={id} value={id} data-testid={`office-rules-subtab-${id}`}>
              {t(RULE_SUBTAB_LABEL_KEYS[id])}
            </TabsTrigger>
          ))}
        </TabsList>

        {RULE_SUBTAB_IDS.map((id) => (
          <TabsContent
            key={id}
            value={id}
            forceMount
            hidden={activeSubtab !== id}
            data-testid={`office-rules-panel-${id}`}
          >
            {mounted.includes(id) && id === 'rules-library' ? (
              <div className="space-y-4">
                {draftRuleCount > 0 && !isDraftOpen && (
                  <div
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs"
                    data-testid="office-rules-resume-draft"
                  >
                    <span className="text-text">
                      📝 有未完成的抽取草稿（{draftRuleCount} 条
                      {draftSourceName ? ` · ${draftSourceName}` : ''}）
                    </span>
                    <button
                      type="button"
                      onClick={resumeDraft}
                      className="rounded bg-primary px-2.5 py-1 text-ui-2xs text-white hover:bg-primary/90"
                    >
                      继续编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm('确定丢弃这份草稿吗？')) {
                          resetDraft();
                        }
                      }}
                      className="rounded border border-border px-2.5 py-1 text-ui-2xs text-text-secondary hover:bg-bg-hover"
                    >
                      丢弃
                    </button>
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleExtractFromActiveDocument()}
                    disabled={!activeDocument || extracting}
                    title={activeDocument ? undefined : t('office.rules.extractFromDoc.hint')}
                    data-testid="office-rules-extract-from-doc"
                    className="inline-flex items-center gap-1.5 rounded border border-primary/40 bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50 disabled:hover:bg-primary/10"
                  >
                    {extracting && (
                      <span
                        className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"
                        data-testid="office-rules-extract-spinner"
                        aria-hidden="true"
                      />
                    )}
                    {extracting ? t('office.rules.extractBusy') : t('office.rules.extractFromDoc')}
                  </button>
                  {!activeDocument && (
                    <span className="text-xs text-muted">
                      {t('office.rules.extractFromDoc.hint')}
                    </span>
                  )}
                </div>

                <RulesWorkspace
                  workspacePath={workspacePath}
                  filePath={documentPath}
                  reloadKey={reloadKey}
                  focusGroupId={focusGroupId}
                />

                {/* External rule sources — a reference drawer, not a peer panel. */}
                <details
                  className="rounded-lg border border-border bg-surface"
                  data-testid="office-rules-spec-library"
                >
                  <summary className="cursor-pointer px-3 py-2 text-sm text-text-secondary">
                    {t('office.rules.specLibraryToggle')}
                  </summary>
                  <div className="px-3 pb-3">
                    <OfficeSpecLibrary workspacePath={workspacePath} />
                  </div>
                </details>
              </div>
            ) : null}

            {mounted.includes(id) && id === 'ai-audit' ? (
              <AiAuditTab workspacePath={workspacePath} />
            ) : null}

            {mounted.includes(id) && id === 'batch-tools' ? (
              <BatchToolsTab workspacePath={workspacePath} onGoToDocuments={onGoToDocuments} />
            ) : null}
          </TabsContent>
        ))}
      </Tabs>

      <RuleExtractionDraft onCommitted={handleCommitted} />
    </div>
  );
}
