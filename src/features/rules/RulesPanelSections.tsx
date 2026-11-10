// src/features/rules/RulesPanelSections.tsx
/**
 * Presentational subcomponents of the rules panel.
 * Split out so RulesPanel.tsx stays below the 400-line file cap.
 */
import { type RuleEntry } from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';

import { RuleRow, type RuleAction } from './RuleRow';
import { buildRuleGroups, layerLabelKey, type LayerFilter } from './rulesView';

const FILTERS: readonly LayerFilter[] = ['all', 'constraint', 'playbook', 'doc', 'global'];

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
        title={t('rules.health.conflictsHint')}
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
  onOpenAi: () => void;
}

export function RulesHeader({
  enabledCount,
  conflictCount,
  loading,
  onOpenDrawer,
  onRefresh,
  onCreate,
  onOpenAi,
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
        <Button variant="secondary" size="sm" onClick={onOpenAi} data-testid="rules-ai-open">
          {t('rules.ai.open')}
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

export function RulesFilterBar({ search, onSearch, layer, onLayer }: RulesFilterBarProps) {
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

interface RulesStatusNoticesProps {
  loading: boolean;
  error: string | null;
  hasRules: boolean;
  filteredEmpty: boolean;
  onRetry: () => void;
}

export function RulesStatusNotices({
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

interface RuleGroupListProps {
  groups: ReturnType<typeof buildRuleGroups>;
  conflicted: Set<string>;
  onOpenSource?: (entry: RuleEntry) => void;
  onAction?: (action: RuleAction, entry: RuleEntry) => void;
}

export function RuleGroupList({ groups, conflicted, onOpenSource, onAction }: RuleGroupListProps) {
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
