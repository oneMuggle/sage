import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, useMemo } from 'react';

import type { RuleConflict, RuleEntry } from '../../shared/api/rulesApi';
import { useI18n } from '../../shared/lib/i18n';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

import { conflictedRuleIds, layerLabelKey, sortEffectiveRules, sourceDetail } from './rulesView';

export interface EffectiveRulesDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  entries: readonly RuleEntry[];
  conflicts: readonly RuleConflict[];
}

function DrawerHeader({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3">
      <div className="space-y-1">
        <Dialog.Title as="h3" className="text-sm font-semibold text-foreground">
          {t('rules.drawer.title')}
        </Dialog.Title>
        <p className="text-ui-2xs text-muted-foreground">{t('rules.drawer.description')}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label={t('rules.action.close')}
        data-testid="rules-effective-close"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

function EffectiveRuleRow({
  entry,
  index,
  conflicted,
}: {
  entry: RuleEntry;
  index: number;
  conflicted: boolean;
}) {
  const { t } = useI18n();
  const detail = sourceDetail(entry);
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-border px-3 py-2"
      data-testid={`rules-effective-row-${entry.id}`}
    >
      <span className="mt-0.5 w-6 shrink-0 text-right font-mono text-ui-2xs text-muted-foreground">
        {index + 1}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{t(layerLabelKey(entry.layer))}</Badge>
          {detail && (
            <span
              className={
                detail.title
                  ? 'font-mono text-ui-2xs text-muted-foreground'
                  : 'text-ui-2xs text-muted-foreground'
              }
              title={detail.title}
            >
              {detail.text}
            </span>
          )}
          {entry.id.includes(':check:') && (
            <span className="text-ui-2xs text-muted-foreground">
              {t('rules.drawer.checkLabel')}
            </span>
          )}
          {conflicted && (
            <span
              className="text-ui-2xs text-amber-600"
              data-testid={`rules-effective-conflict-${entry.id}`}
            >
              {t('rules.row.conflict')}
            </span>
          )}
        </div>
        <p className="truncate text-xs text-foreground" title={entry.content}>
          {entry.content}
        </p>
      </div>
    </div>
  );
}

function DrawerBody({
  ordered,
  conflicted,
}: {
  ordered: readonly RuleEntry[];
  conflicted: Set<string>;
}) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-5 py-3">
      {ordered.length === 0 ? (
        <p
          className="py-6 text-center text-xs text-muted-foreground"
          data-testid="rules-effective-empty"
        >
          {t('rules.drawer.empty')}
        </p>
      ) : (
        ordered.map((entry, index) => (
          <EffectiveRuleRow
            key={entry.id}
            entry={entry}
            index={index}
            conflicted={conflicted.has(entry.id)}
          />
        ))
      )}
    </div>
  );
}

function DrawerPanelBody({
  onClose,
  ordered,
  conflicted,
}: {
  onClose: () => void;
  ordered: readonly RuleEntry[];
  conflicted: Set<string>;
}) {
  const { t } = useI18n();
  return (
    <>
      <DrawerHeader onClose={onClose} />
      <DrawerBody ordered={ordered} conflicted={conflicted} />
      <div className="border-t border-border px-5 py-2 text-ui-2xs text-muted-foreground">
        {t('rules.drawer.order')}
      </div>
    </>
  );
}

export function EffectiveRulesDrawer({
  isOpen,
  onClose,
  entries,
  conflicts,
}: EffectiveRulesDrawerProps) {
  const ordered = useMemo(() => sortEffectiveRules(entries), [entries]);
  const conflicted = useMemo(() => conflictedRuleIds(conflicts), [conflicts]);

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-overlay" />
        </Transition.Child>

        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200"
            enterFrom="opacity-0 scale-95"
            enterTo="opacity-100 scale-100"
            leave="ease-in duration-150"
            leaveFrom="opacity-100 scale-100"
            leaveTo="opacity-0 scale-95"
          >
            <Dialog.Panel
              className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-surface-elevated shadow-xl dark:bg-surface"
              data-testid="rules-effective-drawer"
            >
              <DrawerPanelBody onClose={onClose} ordered={ordered} conflicted={conflicted} />
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}
