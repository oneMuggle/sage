// src/features/office/rules/RulesWorkspace.tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { officeRulesApi } from '../../../shared/api/officeRulesApi';
import type { WireRuleInput } from '../../../shared/api/types';
import { useI18n } from '../../../shared/lib/i18n';
import type { TranslationKey } from '../../../shared/lib/i18n';
import { downloadPlaybookText } from '../../playbook/playbookDownload';

import { ConflictDialog } from './ConflictDialog';
import { RuleAuditResults } from './RuleAuditResults';
import { RuleDetailPanel } from './RuleDetailPanel';
import { RuleGroupList } from './RuleGroupList';
import { RulePackBar } from './RulePackBar';
import {
  auditResultFromWire,
  conflictsFromWire,
  importResultFromWire,
  ruleFieldsToWire,
  ruleGroupsFromWire,
  rulePackFromWire,
  rulePackToWire,
} from './ruleMapping';
import { rulePackToMarkdown } from './rulePackMarkdown';
import {
  RulePackParseError,
  parseRulePack,
  rulePackFileName,
  serializeRulePack,
} from './rulePackSerialization';
import type { RuleAuditResult, RuleConflict, RuleFields, RuleGroup } from './ruleTypes';

export interface RulesWorkspaceProps {
  workspacePath: string;
  filePath: string | null;
  /**
   * Bump to refetch the group list. The parent (`RulesSubtabs`) uses this
   * after it extracts rules into a brand-new group.
   */
  reloadKey?: number;
  /** Group to select once the list has been (re)loaded. */
  focusGroupId?: string | null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function importErrorMessage(error: unknown, t: (key: TranslationKey) => string): string {
  if (error instanceof RulePackParseError) {
    if (error.code === 'invalid-json') return t('office.rules.importError.invalidJson');
    if (error.code === 'invalid-shape') return t('office.rules.importError.invalidShape');
    if (error.code === 'too-many-rules') return t('office.rules.importError.tooManyRules');
    if (error.code === 'invalid-field') {
      const fieldPart = error.field ? `: ${error.field}` : '';
      return `${t('office.rules.importError.invalidField')}${fieldPart}`;
    }
  }
  return errorMessage(error);
}

const MAX_IMPORT_PACK_BYTES = 5 * 1024 * 1024;

export function RulesWorkspace({
  workspacePath,
  filePath,
  reloadKey,
  focusGroupId,
}: RulesWorkspaceProps) {
  const { t } = useI18n();
  const [groups, setGroups] = useState<RuleGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [auditing, setAuditing] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [conflicts, setConflicts] = useState<RuleConflict[] | null>(null);
  const [auditResult, setAuditResult] = useState<RuleAuditResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setGroups(ruleGroupsFromWire(await officeRulesApi.listGroups()));
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  // Selecting the group the parent just created is safe before the list
  // arrives: `selectedGroup` falls back to the first group and re-resolves
  // once `groups` has been populated.
  useEffect(() => {
    if (!focusGroupId) return;
    setSelectedGroupId(focusGroupId);
    setSelectedRuleId(null);
    setCreating(false);
  }, [focusGroupId]);

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? groups[0] ?? null,
    [groups, selectedGroupId],
  );
  // The detail form is only useful once a rule is in focus; fall back to the
  // first rule of the selected group so the panel is populated on first load.
  const selectedRule = useMemo(() => {
    if (!selectedGroup || creating) return null;
    const explicit = selectedGroup.rules.find((rule) => rule.id === selectedRuleId);
    return explicit ?? selectedGroup.rules[0] ?? null;
  }, [selectedGroup, selectedRuleId, creating]);

  const ruleNameById = useCallback(
    (id: string) => {
      for (const group of groups) {
        const match = group.rules.find((rule) => rule.id === id);
        if (match) return match.name;
      }
      return id;
    },
    [groups],
  );

  const handleSelectGroup = (id: string) => {
    setSelectedGroupId(id);
    setSelectedRuleId(null);
    setCreating(false);
    setAuditResult(null);
  };

  const handleSelectRule = (id: string) => {
    setSelectedRuleId(id);
    setCreating(false);
  };

  const handleToggleCreateRule = () => {
    setCreating((value) => !value);
    setSelectedRuleId(null);
  };

  const handleCreateGroup = async (name: string, description: string, priority: number) => {
    setBusy(true);
    try {
      const created = await officeRulesApi.createGroup({ name, description, priority });
      await load();
      setSelectedGroupId(created.id);
      setSelectedRuleId(null);
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateGroup = async (
    groupId: string,
    patch: { name?: string; description?: string; priority?: number },
  ) => {
    setBusy(true);
    try {
      await officeRulesApi.updateGroup(groupId, patch);
      await load();
    } catch (error) {
      toast.error(`${t('office.rules.group.saveFailed')}: ${errorMessage(error)}`);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteGroup = async (groupId: string) => {
    setBusy(true);
    try {
      await officeRulesApi.deleteGroup(groupId);
      await load();
      setSelectedGroupId(null);
      setSelectedRuleId(null);
      setCreating(false);
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateRule = async (fields: RuleFields) => {
    if (!selectedGroup) return;
    setBusy(true);
    try {
      // RuleFields is the complete editable rule, so the wire patch is a full input.
      const wire = ruleFieldsToWire(fields) as WireRuleInput;
      const created = await officeRulesApi.createRule(selectedGroup.id, wire);
      await load();
      setSelectedGroupId(selectedGroup.id);
      setSelectedRuleId(created.id);
      setCreating(false);
      toast.success(t('office.rules.detail.saved'));
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateRule = async (ruleId: string, fields: Partial<RuleFields>) => {
    setBusy(true);
    try {
      // PUT behaves as a PATCH: send only fields that actually changed.
      const existing = groups.flatMap((group) => group.rules).find((rule) => rule.id === ruleId);
      const changed: Partial<RuleFields> = {};
      if (existing) {
        if (fields.name !== undefined && fields.name !== existing.name) changed.name = fields.name;
        if (fields.type !== undefined && fields.type !== existing.type) changed.type = fields.type;
        if (fields.severity !== undefined && fields.severity !== existing.severity) {
          changed.severity = fields.severity;
        }
        if (fields.scope !== undefined && fields.scope !== existing.scope) {
          changed.scope = fields.scope;
        }
        if (fields.description !== undefined && fields.description !== existing.description) {
          changed.description = fields.description;
        }
        if (fields.checkMode !== undefined && fields.checkMode !== existing.checkMode) {
          changed.checkMode = fields.checkMode;
        }
        if (fields.pattern !== undefined && fields.pattern !== (existing.pattern ?? '')) {
          changed.pattern = fields.pattern;
        }
        if (fields.aiPrompt !== undefined && fields.aiPrompt !== (existing.aiPrompt ?? '')) {
          changed.aiPrompt = fields.aiPrompt;
        }
        if (fields.enabled !== undefined && fields.enabled !== existing.enabled) {
          changed.enabled = fields.enabled;
        }
      } else {
        Object.assign(changed, fields);
      }
      await officeRulesApi.updateRule(ruleId, ruleFieldsToWire(changed));
      await load();
      toast.success(t('office.rules.detail.saved'));
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    setBusy(true);
    try {
      await officeRulesApi.deleteRule(ruleId);
      await load();
      setSelectedRuleId(null);
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleCheckConflicts = async () => {
    if (!selectedGroup) return;
    if (selectedGroup.rules.length < 2) {
      toast.error(t('office.rules.workspace.conflictsNeedTwo'));
      return;
    }
    setBusy(true);
    try {
      const result = await officeRulesApi.checkConflicts(
        selectedGroup.rules.map((rule) => rule.id),
      );
      const list = conflictsFromWire(result.conflicts);
      if (list.length === 0) {
        toast.success(t('office.rules.workspace.conflictsEmpty'));
      } else {
        setConflicts(list);
      }
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    if (!selectedGroup) return;
    setBusy(true);
    try {
      const wire = await officeRulesApi.exportPack({
        group_ids: [selectedGroup.id],
        name: selectedGroup.name,
      });
      const pack = rulePackFromWire(wire);
      downloadPlaybookText(
        rulePackFileName(selectedGroup.name),
        serializeRulePack(pack),
        'application/json',
      );
      toast.success(t('office.rules.workspace.exported'));
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async (file: File) => {
    setBusy(true);
    try {
      if (file.size > MAX_IMPORT_PACK_BYTES) {
        toast.error(t('office.rules.workspace.importTooLarge'));
        return;
      }
      const pack = parseRulePack(await file.text());
      const result = importResultFromWire(await officeRulesApi.importPack(rulePackToWire(pack)));
      await load();
      toast.success(`${t('office.rules.workspace.imported')} (${result.importedRules})`);
    } catch (error) {
      toast.error(`${t('office.rules.workspace.importFailed')}: ${importErrorMessage(error, t)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleAudit = async () => {
    if (!workspacePath || !filePath) {
      toast.error(t('office.rules.workspace.auditNeedsFile'));
      return;
    }
    const ruleIds = (selectedGroup?.rules ?? [])
      .filter((rule) => rule.enabled)
      .map((rule) => rule.id);
    if (ruleIds.length === 0) {
      toast.error(t('office.rules.workspace.auditNoRules'));
      return;
    }
    setAuditing(true);
    setAuditResult(null);
    try {
      setAuditResult(
        auditResultFromWire(
          await officeRulesApi.audit({
            workspace_path: workspacePath,
            file_path: filePath,
            rule_ids: ruleIds,
          }),
        ),
      );
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setAuditing(false);
    }
  };

  const handleExportMarkdown = async () => {
    if (!selectedGroup) return;
    setBusy(true);
    try {
      const wire = await officeRulesApi.exportPack({
        group_ids: [selectedGroup.id],
        name: selectedGroup.name,
      });
      const pack = rulePackFromWire(wire);
      downloadPlaybookText(
        rulePackFileName(selectedGroup.name).replace(/\.sage-rules$/, '.md'),
        rulePackToMarkdown(pack),
        'text/markdown',
      );
      toast.success(t('office.rules.workspace.exportedMarkdown'));
    } catch (error) {
      toast.error(`${t('office.rules.workspace.operationFailed')}: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const locked = busy || auditing;

  return (
    <section data-testid="office-rules-workspace" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-text">{t('office.rules.workspace.title')}</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="rules-audit"
            disabled={locked || !filePath}
            title={filePath ? undefined : t('office.rules.workspace.auditNeedsFile')}
            className="rounded bg-primary px-3 py-1.5 text-sm text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            onClick={() => void handleAudit()}
          >
            {auditing ? t('office.rules.workspace.auditing') : t('office.rules.workspace.audit')}
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-xs text-muted" data-testid="rules-loading">
          {t('office.rules.workspace.loading')}
        </p>
      ) : null}

      {loadError ? (
        <div
          className="rounded border border-border bg-bg-subtle p-3 text-xs text-text-secondary"
          data-testid="rules-load-error"
        >
          <p>
            {t('office.rules.workspace.loadFailed')}: {loadError}
          </p>
          <button
            type="button"
            data-testid="rules-retry"
            className="mt-2 underline"
            onClick={() => void load()}
          >
            {t('office.rules.workspace.retry')}
          </button>
        </div>
      ) : null}

      {!loading && !loadError ? (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-1">
              <RuleGroupList
                groups={groups}
                selectedGroupId={selectedGroup?.id ?? null}
                selectedRuleId={creating ? null : (selectedRule?.id ?? null)}
                creatingRule={creating}
                busy={locked}
                onSelect={handleSelectGroup}
                onSelectRule={handleSelectRule}
                onCreateRule={handleToggleCreateRule}
                onCreate={(name, description, priority) =>
                  handleCreateGroup(name, description, priority)
                }
                onUpdate={(groupId, patch) => handleUpdateGroup(groupId, patch)}
                onDelete={(id) => void handleDeleteGroup(id)}
              />
            </div>
            <div className="lg:col-span-2">
              <RuleDetailPanel
                key={
                  creating
                    ? `new-${selectedGroup?.id ?? 'none'}`
                    : (selectedRule?.id ?? `new-${selectedGroup?.id ?? 'none'}`)
                }
                group={selectedGroup}
                rule={selectedRule}
                busy={locked}
                onCreate={(fields) => void handleCreateRule(fields)}
                onUpdate={(ruleId, fields) => void handleUpdateRule(ruleId, fields)}
                onDelete={(ruleId) => void handleDeleteRule(ruleId)}
              />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RulePackBar
              group={selectedGroup}
              busy={locked}
              onExport={() => void handleExport()}
              onExportMarkdown={() => void handleExportMarkdown()}
              onImport={(file) => void handleImport(file)}
              onCheckConflicts={() => void handleCheckConflicts()}
            />
            <RuleAuditResults result={auditResult} auditing={auditing} />
          </div>
        </>
      ) : null}

      {conflicts ? (
        <ConflictDialog
          conflicts={conflicts}
          ruleNameById={ruleNameById}
          onClose={() => setConflicts(null)}
        />
      ) : null}
    </section>
  );
}
