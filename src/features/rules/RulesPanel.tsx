import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  rulesApi,
  type RuleConflict,
  type RuleEntry,
} from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';

import { EffectiveRulesDrawer } from './EffectiveRulesDrawer';
import { RuleRow } from './RuleRow';
import {
  buildRuleGroups,
  conflictedRuleIds,
  countEnabled,
  filterRules,
  layerLabelKey,
  type LayerFilter,
} from './rulesView';

const FILTERS: readonly LayerFilter[] = ['all', 'constraint', 'playbook', 'doc', 'global'];

export interface RulesPanelProps {
  projectId: string;
  onOpenSource?: (entry: RuleEntry) => void;
}

interface RulesData {
  rules: RuleEntry[];
  conflicts: RuleConflict[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

function useRulesData(projectId: string): RulesData {
  const [rules, setRules] = useState<RuleEntry[]>([]);
  const [conflicts, setConflicts] = useState<RuleConflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, effective] = await Promise.all([
        rulesApi.list(projectId),
        rulesApi.effective(projectId),
      ]);
      setRules(list);
      setConflicts(effective.conflicts);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { rules, conflicts, loading, error, reload };
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
}

function RulesHeader({
  enabledCount,
  conflictCount,
  loading,
  onOpenDrawer,
  onRefresh,
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
        className="max-w-xs"
        data-testid="rules-search"
      />
      {FILTERS.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onLayer(id)}
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

function RulesEmptyFiltered({ filtered }: { filtered: boolean }) {
  const { t } = useI18n();
  return (
    <p className="px-1 text-ui-2xs text-muted-foreground" data-testid="rules-empty-filtered">
      {filtered ? t('rules.empty.filtered') : t('rules.empty.title')}
    </p>
  );
}

interface RuleGroupListProps {
  groups: ReturnType<typeof buildRuleGroups>;
  conflicted: Set<string>;
  onOpenSource?: (entry: RuleEntry) => void;
}

function RuleGroupList({ groups, conflicted, onOpenSource }: RuleGroupListProps) {
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
              />
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

export function RulesPanel({ projectId, onOpenSource }: RulesPanelProps) {
  const { t } = useI18n();
  const { rules, conflicts, loading, error, reload } = useRulesData(projectId);
  const [search, setSearch] = useState('');
  const [layer, setLayer] = useState<LayerFilter>('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const conflicted = useMemo(() => conflictedRuleIds(conflicts), [conflicts]);
  const groups = useMemo(
    () => buildRuleGroups(filterRules(rules, { search, layer })),
    [rules, search, layer],
  );
  const enabledCount = countEnabled(rules);
  const filtered = search.trim().length > 0 || layer !== 'all';
  const hasRules = rules.length > 0;

  return (
    <div className="space-y-3" data-testid="rules-panel">
      <RulesHeader
        enabledCount={enabledCount}
        conflictCount={conflicts.length}
        loading={loading}
        onOpenDrawer={() => setDrawerOpen(true)}
        onRefresh={() => void reload()}
      />
      <RulesFilterBar search={search} onSearch={setSearch} layer={layer} onLayer={setLayer} />
      {loading && (
        <p className="text-ui-2xs text-muted-foreground" data-testid="rules-loading">
          {t('rules.loading')}
        </p>
      )}
      {error && <RulesErrorNotice message={error} onRetry={() => void reload()} />}
      {!loading && !error && !hasRules && <RulesEmpty />}
      {!loading && !error && hasRules && groups.length === 0 && (
        <RulesEmptyFiltered filtered={filtered} />
      )}
      <RuleGroupList groups={groups} conflicted={conflicted} onOpenSource={onOpenSource} />
      <EffectiveRulesDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        entries={rules}
        conflicts={conflicts}
      />
    </div>
  );
}
