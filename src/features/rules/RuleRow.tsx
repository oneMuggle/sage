import { Lock, MoreHorizontal } from 'lucide-react';

import type { RuleEntry } from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../../shared/ui/DropdownMenu/DropdownMenu';

import { layerLabelKey } from './rulesView';

export type RuleAction = 'edit' | 'copy' | 'toggle' | 'delete';

export interface RuleRowProps {
  entry: RuleEntry;
  conflicted?: boolean;
  onOpenSource?: (entry: RuleEntry) => void;
  onAction?: (action: RuleAction, entry: RuleEntry) => void;
}

function RuleChips({ entry, conflicted }: { entry: RuleEntry; conflicted: boolean }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="secondary">{t(layerLabelKey(entry.layer))}</Badge>
      <span className="text-ui-2xs text-muted-foreground">{entry.sourceLabel}</span>
      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-ui-2xs text-muted-foreground">
        {entry.category}
      </span>
      {conflicted && (
        <span
          className="rounded bg-amber-500/15 px-1.5 py-0.5 text-ui-2xs text-amber-600"
          data-testid={`rule-conflict-${entry.id}`}
        >
          {t('rules.row.conflict')}
        </span>
      )}
      {entry.editable !== 'full' && (
        <span
          className="inline-flex items-center gap-0.5 text-ui-2xs text-muted-foreground"
          data-testid={`rule-lock-${entry.id}`}
        >
          <Lock className="h-3 w-3" />
          {t('rules.row.readonly')}
        </span>
      )}
    </div>
  );
}

function RuleMeta({ entry }: { entry: RuleEntry }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-3 text-ui-2xs text-muted-foreground">
      <span>{entry.scope}</span>
      {entry.trigger && <span>{t('rules.row.trigger').replace('{trigger}', entry.trigger)}</span>}
      <span>{t('rules.row.priority').replace('{priority}', String(entry.priority))}</span>
      <span className={entry.enabled ? 'text-emerald-600' : undefined}>
        {entry.enabled ? t('rules.row.enabled') : t('rules.row.disabled')}
      </span>
    </div>
  );
}

interface RuleMenuProps {
  entry: RuleEntry;
  onAction: (action: RuleAction, entry: RuleEntry) => void;
}

/** 「···」菜单：只读行仅保留复制。 */
function RuleMenu({ entry, onAction }: RuleMenuProps) {
  const { t } = useI18n();
  const writable = entry.editable === 'full';
  const canToggle = writable && entry.layer === 'constraint';

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('rules.menu.label')}
          data-testid={`rule-menu-${entry.id}`}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {writable ? (
          <DropdownMenuItem
            onSelect={() => onAction('edit', entry)}
            data-testid={`rule-menu-edit-${entry.id}`}
          >
            {t('rules.menu.edit')}
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem disabled>{t('rules.menu.edit')}</DropdownMenuItem>
        )}
        <DropdownMenuItem
          onSelect={() => onAction('copy', entry)}
          data-testid={`rule-menu-copy-${entry.id}`}
        >
          {t('rules.menu.copy')}
        </DropdownMenuItem>
        {canToggle && (
          <DropdownMenuItem
            onSelect={() => onAction('toggle', entry)}
            data-testid={`rule-menu-toggle-${entry.id}`}
          >
            {entry.enabled ? t('rules.menu.disable') : t('rules.menu.enable')}
          </DropdownMenuItem>
        )}
        {writable && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onAction('delete', entry)}
              data-testid={`rule-menu-delete-${entry.id}`}
            >
              {t('rules.menu.delete')}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** 单条规则；写操作通过「···」菜单触发，由 RulesPanel 统一处理。 */
export function RuleRow({ entry, conflicted = false, onOpenSource, onAction }: RuleRowProps) {
  const { t } = useI18n();
  const showSource = Boolean(onOpenSource) && entry.layer === 'playbook';

  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2"
      data-testid={`rule-row-${entry.id}`}
    >
      <div className="min-w-0 flex-1 space-y-1">
        <RuleChips entry={entry} conflicted={conflicted} />
        <p className="truncate text-xs text-foreground" title={entry.content}>
          {entry.content}
        </p>
        <RuleMeta entry={entry} />
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {showSource && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenSource?.(entry)}
            data-testid={`rule-source-${entry.id}`}
          >
            {t('rules.row.openSource')}
          </Button>
        )}
        {onAction && <RuleMenu entry={entry} onAction={onAction} />}
      </div>
    </div>
  );
}
