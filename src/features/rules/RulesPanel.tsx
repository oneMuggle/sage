// src/features/rules/RulesPanel.tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { rulesApi, type RuleConflict, type RuleEntry } from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { EffectiveRulesDrawer } from './EffectiveRulesDrawer';
import { RuleEditorDialog } from './RuleEditorDialog';
import { type RuleAction } from './RuleRow';
import {
  RuleGroupList,
  RulesFilterBar,
  RulesHeader,
  RulesStatusNotices,
} from './RulesPanelSections';
import {
  buildRuleGroups,
  conflictedRuleIds,
  countEnabled,
  filterRules,
  isConflictError,
  type LayerFilter,
} from './rulesView';

export interface RulesPanelProps {
  projectId: string;
  onOpenSource?: (entry: RuleEntry) => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type Translate = (key: TranslationKey) => string;

function failureMessage(t: Translate, key: TranslationKey, err: unknown): string {
  return t(key).replace('{message}', errorMessage(err));
}

function reportConflict(t: Translate): void {
  toast.error(t('rules.conflict.reload'));
}

interface RulesData {
  rules: RuleEntry[];
  effectiveEntries: RuleEntry[];
  conflicts: RuleConflict[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useRulesData(projectId: string): RulesData {
  const [rules, setRules] = useState<RuleEntry[]>([]);
  const [effectiveEntries, setEffectiveEntries] = useState<RuleEntry[]>([]);
  const [conflicts, setConflicts] = useState<RuleConflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [list, effective] = await Promise.all([
          rulesApi.list(projectId),
          rulesApi.effective(projectId),
        ]);
        if (!active) return;
        setRules(list);
        setEffectiveEntries(effective.entries);
        setConflicts(effective.conflicts);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [projectId, reloadToken]);

  return { rules, effectiveEntries, conflicts, loading, error, reload };
}

async function copyRuleContent(entry: RuleEntry, t: Translate): Promise<void> {
  try {
    await navigator.clipboard.writeText(entry.content);
    toast.success(t('rules.action.copied'));
  } catch (err) {
    toast.error(failureMessage(t, 'rules.action.copyFailed', err));
  }
}

async function toggleRule(
  projectId: string,
  entry: RuleEntry,
  reload: () => void,
  t: Translate,
): Promise<void> {
  try {
    await rulesApi.update(projectId, {
      layer: 'constraint',
      ruleId: entry.id,
      patch: { enabled: !entry.enabled },
      expectedUpdatedAt: entry.updatedAt,
    });
    reload();
  } catch (err) {
    if (isConflictError(err)) {
      reload();
      reportConflict(t);
      return;
    }
    toast.error(failureMessage(t, 'rules.action.toggleFailed', err));
  }
}

async function deleteRule(
  projectId: string,
  entry: RuleEntry,
  reload: () => void,
  t: Translate,
): Promise<void> {
  const confirmed = await confirmDialog({
    title: t('rules.delete.title'),
    message: t('rules.delete.message'),
    confirmLabel: t('rules.delete.confirm'),
    cancelLabel: t('rules.editor.cancel'),
    danger: true,
  });
  if (!confirmed) return;
  try {
    await rulesApi.remove(projectId, entry.layer, entry.id);
    toast.success(t('rules.action.deleted'));
    reload();
  } catch (err) {
    if (isConflictError(err)) {
      reload();
      reportConflict(t);
      return;
    }
    toast.error(failureMessage(t, 'rules.action.deleteFailed', err));
  }
}

function useRuleEditor() {
  const [editorOpen, setEditorOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<RuleEntry | null>(null);

  const openCreate = useCallback(() => {
    setEditTarget(null);
    setEditorOpen(true);
  }, []);

  const closeEditor = useCallback(() => {
    setEditorOpen(false);
    setEditTarget(null);
  }, []);

  return { editorOpen, editTarget, setEditTarget, setEditorOpen, openCreate, closeEditor };
}

/** 新建 / 编辑 / 复制 / 停用 / 删除的状态与副作用。 */
function useRuleWrites(projectId: string, reload: () => void) {
  const { t } = useI18n();
  const { editorOpen, editTarget, setEditTarget, setEditorOpen, openCreate, closeEditor } =
    useRuleEditor();

  const handleSaved = useCallback(async () => {
    toast.success(t('rules.action.saved'));
    reload();
  }, [reload, t]);

  const handleAction = useCallback(
    async (action: RuleAction, entry: RuleEntry) => {
      if (action === 'edit') {
        setEditTarget(entry);
        setEditorOpen(true);
      } else if (action === 'copy') {
        await copyRuleContent(entry, t);
      } else if (action === 'toggle') {
        await toggleRule(projectId, entry, reload, t);
      } else {
        await deleteRule(projectId, entry, reload, t);
      }
    },
    [projectId, reload, setEditTarget, setEditorOpen, t],
  );

  return { editorOpen, editTarget, openCreate, closeEditor, handleSaved, handleAction };
}

function useRulesPanelState(projectId: string) {
  const { rules, effectiveEntries, conflicts, loading, error, reload } = useRulesData(projectId);
  const [search, setSearch] = useState('');
  const [layer, setLayer] = useState<LayerFilter>('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const writes = useRuleWrites(projectId, reload);
  const conflicted = useMemo(() => conflictedRuleIds(conflicts), [conflicts]);
  const groups = useMemo(
    () => buildRuleGroups(filterRules(rules, { search, layer })),
    [rules, search, layer],
  );
  return {
    rules,
    effectiveEntries,
    conflicts,
    loading,
    error,
    reload,
    search,
    setSearch,
    layer,
    setLayer,
    drawerOpen,
    setDrawerOpen,
    conflicted,
    groups,
    ...writes,
  };
}

export function RulesPanel({ projectId, onOpenSource }: RulesPanelProps) {
  const state = useRulesPanelState(projectId);

  return (
    <div className="space-y-3" data-testid="rules-panel">
      <RulesHeader
        enabledCount={countEnabled(state.rules)}
        conflictCount={state.conflicts.length}
        loading={state.loading}
        onOpenDrawer={() => state.setDrawerOpen(true)}
        onRefresh={state.reload}
        onCreate={state.openCreate}
      />
      <RulesFilterBar
        search={state.search}
        onSearch={state.setSearch}
        layer={state.layer}
        onLayer={state.setLayer}
      />
      <RulesStatusNotices
        loading={state.loading}
        error={state.error}
        hasRules={state.rules.length > 0}
        filteredEmpty={state.groups.length === 0}
        onRetry={state.reload}
      />
      <RuleGroupList
        groups={state.groups}
        conflicted={state.conflicted}
        onOpenSource={onOpenSource}
        onAction={(action, entry) => void state.handleAction(action, entry)}
      />
      <RuleEditorDialog
        isOpen={state.editorOpen}
        onClose={state.closeEditor}
        projectId={projectId}
        entry={state.editTarget}
        onSaved={state.handleSaved}
      />
      <EffectiveRulesDrawer
        isOpen={state.drawerOpen}
        onClose={() => state.setDrawerOpen(false)}
        entries={state.effectiveEntries}
        conflicts={state.conflicts}
      />
    </div>
  );
}
