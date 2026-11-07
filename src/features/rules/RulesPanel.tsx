import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { rulesApi, type RuleConflict, type RuleEntry } from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { Input } from '../../shared/ui/Input';

import { EffectiveRulesDrawer } from './EffectiveRulesDrawer';
import { RuleEditorDialog } from './RuleEditorDialog';
import { RuleRow, type RuleAction } from './RuleRow';
import {
  buildRuleGroups,
  conflictedRuleIds,
  countEnabled,
  filterRules,
  isConflictError,
  layerLabelKey,
  type LayerFilter,
} from './rulesView';

const FILTERS: readonly LayerFilter[] = ['all', 'constraint', 'playbook', 'doc', 'global'];

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

function RulesHealthBadge({
  enabledCount,
  conflictCount,
}: {
  enabledCount: number;
  conflictCount: number;
}) {
  const { t } = useI18n();
  return (
    <span
      className="rounded-full bg-muted px-2.5 py-0.5 text-ui-2xs text-muted-foreground"
      data-testid="rules-health"
    >
      <span data-testid="rules-count-enabled">
        {t('rules.health.enabled').replace('{count}', String(enabledCount))}
      </span>
      <span className="mx-1">·</span>
      <span
        className={conflictCount > 0 ? 'text-amber-600' : undefined}
        data-testid="rules-count-conflicts"
      >
        {conflictCount > 0
          ? t('rules.health.conflicts').replace('{count}', String(conflictCount))
          : t('rules.health.healthy')}
      </span>
    </span>
  );
}

interface RulesHeaderProps {
  enabledCount: number;
  conflictCount: number;
  loading: boolean;
  onOpenDrawer: () => void;
  onRefresh: () => void;
  onCreate: () => void;
}

function RulesHeader({
  enabledCount,
  conflictCount,
  loading,
  onOpenDrawer,
  onRefresh,
  onCreate,
}: RulesHeaderProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <div className="text-sm font-semibold text-foreground">{t('rules.title')}</div>
        <p className="max-w-xl text-ui-2xs text-muted-foreground">{t('rules.subtitle')}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <RulesHealthBadge enabledCount={enabledCount} conflictCount={conflictCount} />
        <Button variant="secondary" size="sm" onClick={onCreate} data-testid="rules-create">
          {t('rules.action.create')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={onOpenDrawer}
          data-testid="rules-effective-open"
        >
          {t('rules.action.openEffective')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRefresh}
          disabled={loading}
          data-testid="rules-refresh"
        >
          {t('rules.action.refresh')}
        </Button>
      </div>
    </div>
  );
}

interface RulesFilterBarProps {
  search: string;
  onSearch: (value: string) => void;
  layer: LayerFilter;
  onLayer: (layer: LayerFilter) => void;
}

function RulesFilterBar({ search, onSearch, layer, onLayer }: RulesFilterBarProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        value={search}
        onChange={(event) => onSearch(event.target.value)}
        placeholder={t('rules.search.placeholder')}
        aria-label={t('rules.search.placeholder')}
        className="max-w-xs"
        data-testid="rules-search"
      />
      {FILTERS.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onLayer(id)}
          aria-pressed={layer === id}
          data-testid={`rules-filter-${id}`}
          className={`rounded-md px-2.5 py-1 text-ui-2xs font-medium transition-colors ${
            layer === id
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'
          }`}
        >
          {t(layerLabelKey(id))}
        </button>
      ))}
    </div>
  );
}

function RulesErrorNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div
      className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2"
      data-testid="rules-error"
    >
      <p className="text-xs text-foreground">
        {t('rules.loadFailed').replace('{message}', message)}
      </p>
      <Button variant="secondary" size="sm" onClick={onRetry} data-testid="rules-retry">
        {t('rules.action.retry')}
      </Button>
    </div>
  );
}

function RulesEmpty() {
  const { t } = useI18n();
  return (
    <div
      className="rounded-lg border border-dashed border-border px-4 py-8 text-center"
      data-testid="rules-empty"
    >
      <p className="text-sm font-medium text-foreground">{t('rules.empty.title')}</p>
      <p className="mt-1 text-ui-2xs text-muted-foreground">{t('rules.empty.hint')}</p>
    </div>
  );
}

function RulesEmptyFiltered() {
  const { t } = useI18n();
  return (
    <p className="px-1 text-ui-2xs text-muted-foreground" data-testid="rules-empty-filtered">
      {t('rules.empty.filtered')}
    </p>
  );
}

interface RuleGroupListProps {
  groups: ReturnType<typeof buildRuleGroups>;
  conflicted: Set<string>;
  onOpenSource?: (entry: RuleEntry) => void;
  onAction?: (action: RuleAction, entry: RuleEntry) => void;
}

function RuleGroupList({ groups, conflicted, onOpenSource, onAction }: RuleGroupListProps) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <details
          key={group.layer}
          open
          className="rounded-lg border border-border bg-card/50"
          data-testid={`rules-group-${group.layer}`}
        >
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-foreground">
            {t(layerLabelKey(group.layer))}
            <span className="ml-1 text-muted-foreground">· {group.entries.length}</span>
          </summary>
          <div className="space-y-1.5 px-2 pb-2">
            {group.entries.map((entry) => (
              <RuleRow
                key={entry.id}
                entry={entry}
                conflicted={conflicted.has(entry.id)}
                onOpenSource={onOpenSource}
                onAction={onAction}
              />
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

interface RulesStatusNoticesProps {
  loading: boolean;
  error: string | null;
  hasRules: boolean;
  filteredEmpty: boolean;
  onRetry: () => void;
}

function RulesStatusNotices({
  loading,
  error,
  hasRules,
  filteredEmpty,
  onRetry,
}: RulesStatusNoticesProps) {
  const { t } = useI18n();
  return (
    <>
      {loading && (
        <p className="text-ui-2xs text-muted-foreground" data-testid="rules-loading">
          {t('rules.loading')}
        </p>
      )}
      {error && <RulesErrorNotice message={error} onRetry={onRetry} />}
      {!loading && !error && !hasRules && <RulesEmpty />}
      {!loading && !error && hasRules && filteredEmpty && <RulesEmptyFiltered />}
    </>
  );
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
