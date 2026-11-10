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
import type { WireRuleInput } from '../../../shared/api/types';
import { useKeepAliveTabs } from '../../../shared/lib/hooks/useKeepAliveTabs';
import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../shared/ui/Tabs';
import { OfficeSpecLibrary } from '../OfficeSpecLibrary';
import { officeDocumentPath } from '../officeDocumentPath';

import { AiAuditTab } from './AiAuditTab';
import { BatchToolsTab } from './BatchToolsTab';
import { RulesWorkspace } from './RulesWorkspace';
import { ruleFieldsToWire, ruleFromWire } from './ruleMapping';

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

/** "deck.pptx" → "deck" — used to name the auto-created rule group. */
function fileBaseName(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
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

  const documentPath = activeDocument ? officeDocumentPath(activeDocument) : null;

  const handleExtractFromActiveDocument = async () => {
    if (!activeDocument || !documentPath) {
      toast.warning(t('office.rules.extractNoActiveDoc'));
      return;
    }
    setExtracting(true);
    let createdGroupId: string | null = null;
    let createdCount = 0;
    let extractedTotal = 0;
    try {
      const result = await officeRulesApi.extractRules({
        workspace_path: workspacePath,
        file_path: documentPath,
        file_type: activeDocument.doc_type,
        use_llm: true,
      });
      result.warnings.slice(0, 3).forEach((warning) => {
        toast.warning(warning.message);
      });
      const extracted = result.rules.map(ruleFromWire);
      extractedTotal = extracted.length;
      if (extracted.length === 0) {
        toast.warning(t('office.rules.workspace.extractEmpty'));
        return;
      }

      const sourceName =
        activeDocument.original_filename ?? activeDocument.generated_filename ?? activeDocument.id;
      const groupName = `${fileBaseName(sourceName)} · ${t('office.rules.workspace.extractGroupName')}`;
      const group = await officeRulesApi.createGroup({
        name: groupName,
        description: '',
        priority: 0,
      });
      createdGroupId = group.id;

      for (const rule of extracted) {
        await officeRulesApi.createRule(group.id, ruleFieldsToWire(rule) as WireRuleInput);
        createdCount += 1;
      }

      setFocusGroupId(group.id);
      setReloadKey((key) => key + 1);
      toast.success(
        t('office.rules.extractSuccess')
          .replace('{n}', String(createdCount))
          .replace('{name}', groupName),
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      if (createdGroupId) {
        // The group exists but some rules failed — surface the partial result
        // and still show the group the user would have got.
        setFocusGroupId(createdGroupId);
        setReloadKey((key) => key + 1);
        toast.error(
          `${t('office.rules.workspace.extractPartial')} (${createdCount}/${extractedTotal}): ${message}`,
        );
      } else {
        toast.error(`${t('office.rules.workspace.operationFailed')}: ${message}`);
      }
    } finally {
      setExtracting(false);
    }
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
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleExtractFromActiveDocument()}
                    disabled={!activeDocument || extracting}
                    title={activeDocument ? undefined : t('office.rules.extractFromDoc.hint')}
                    data-testid="office-rules-extract-from-doc"
                    className="rounded border border-primary/40 bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50 disabled:hover:bg-primary/10"
                  >
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
    </div>
  );
}
