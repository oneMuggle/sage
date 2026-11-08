// src/features/office/rules/RuleGroupList.tsx
import { useState } from 'react';

import { useI18n } from '../../../shared/lib/i18n';

import type { RuleGroup } from './ruleTypes';

export interface RuleGroupListProps {
  groups: RuleGroup[];
  selectedGroupId: string | null;
  selectedRuleId: string | null;
  creatingRule: boolean;
  busy: boolean;
  onSelect: (groupId: string) => void;
  onSelectRule: (ruleId: string) => void;
  onCreateRule: () => void;
  onCreate: (name: string, description: string, priority: number) => void | Promise<void>;
  onUpdate?: (
    groupId: string,
    patch: { name?: string; description?: string; priority?: number },
  ) => void | Promise<void>;
  onDelete: (groupId: string) => void | Promise<void>;
}

const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

type FormMode = { kind: 'closed' } | { kind: 'create' } | { kind: 'edit'; groupId: string };

export function RuleGroupList({
  groups,
  selectedGroupId,
  selectedRuleId,
  creatingRule,
  busy,
  onSelect,
  onSelectRule,
  onCreateRule,
  onCreate,
  onUpdate,
  onDelete,
}: RuleGroupListProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<FormMode>({ kind: 'closed' });
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('0');
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const openCreate = () => {
    setMode({ kind: 'create' });
    setName('');
    setDescription('');
    setPriority('0');
    setError(null);
  };

  const openEdit = (group: RuleGroup) => {
    setMode({ kind: 'edit', groupId: group.id });
    setName(group.name);
    setDescription(group.description);
    setPriority(String(group.priority ?? 0));
    setError(null);
  };

  const closeForm = () => {
    setMode({ kind: 'closed' });
    setName('');
    setDescription('');
    setPriority('0');
    setError(null);
  };

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t('office.rules.group.nameRequired'));
      return;
    }
    setError(null);
    const payload = {
      name: trimmed,
      description: description.trim(),
      priority: Number(priority) || 0,
    };
    if (mode.kind === 'edit' && onUpdate) {
      void Promise.resolve(onUpdate(mode.groupId, payload)).then(
        () => closeForm(),
        () => {
          /* keep form open; parent already toasted */
        },
      );
    } else {
      void Promise.resolve(onCreate(payload.name, payload.description, payload.priority)).then(
        () => closeForm(),
        () => {
          /* keep form open; parent already toasted */
        },
      );
    }
  };

  const searchQuery = search.trim().toLowerCase();
  const activeGroup = groups.find((g) => g.id === selectedGroupId) ?? null;
  const filteredRules =
    activeGroup && searchQuery
      ? activeGroup.rules.filter(
          (rule) =>
            rule.name.toLowerCase().includes(searchQuery) ||
            rule.description.toLowerCase().includes(searchQuery),
        )
      : (activeGroup?.rules ?? []);

  return (
    <section className="space-y-2" data-testid="rules-group-list">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-secondary">{t('office.rules.group.title')}</h3>
        <button
          type="button"
          data-testid="rules-group-create"
          className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
          onClick={() => {
            if (mode.kind === 'closed') openCreate();
            else closeForm();
          }}
        >
          {mode.kind === 'closed' ? t('office.rules.group.create') : t('office.rules.group.cancel')}
        </button>
      </div>

      <input
        type="text"
        data-testid="rules-search-input"
        placeholder={t('office.rules.search.placeholder')}
        className={inputClass}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {mode.kind !== 'closed' ? (
        <div className="space-y-2 rounded border border-border bg-bg-subtle p-3">
          <input
            className={inputClass}
            data-testid="rules-group-name-input"
            placeholder={t('office.rules.group.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className={inputClass}
            data-testid="rules-group-description-input"
            placeholder={t('office.rules.group.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <input
            className={inputClass}
            data-testid="rules-group-priority-input"
            type="number"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          />
          {error ? (
            <p className="text-xs text-error" data-testid="rules-group-error">
              {error}
            </p>
          ) : null}
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="rules-group-create-submit"
              className="rounded bg-primary px-3 py-1.5 text-xs text-text-inverse hover:bg-primary-hover disabled:opacity-50"
              disabled={busy}
              onClick={submit}
            >
              {mode.kind === 'edit' ? t('office.rules.group.edit') : t('office.rules.group.submit')}
            </button>
            <button
              type="button"
              className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover"
              onClick={closeForm}
            >
              {t('office.rules.group.cancel')}
            </button>
          </div>
        </div>
      ) : null}

      {groups.length === 0 ? (
        <p className="text-xs text-muted" data-testid="rules-group-empty">
          {t('office.rules.group.empty')}
        </p>
      ) : (
        <ul className="space-y-1">
          {groups.map((group) => {
            const active = group.id === selectedGroupId;
            return (
              <li key={group.id} className="space-y-1">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    data-testid={`rules-group-item-${group.id}`}
                    aria-current={active ? 'true' : undefined}
                    className={`flex-1 rounded border px-2 py-1.5 text-left text-xs ${
                      active
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-text-secondary hover:bg-bg-hover'
                    }`}
                    onClick={() => onSelect(group.id)}
                  >
                    <span className="block font-medium text-text">{group.name}</span>
                    <span className="block text-muted">
                      {group.rules.length} {t('office.rules.workspace.rulesCount')}
                      {group.builtin ? ` · ${t('office.rules.workspace.builtin')}` : ''}
                    </span>
                  </button>
                  {group.builtin ? null : (
                    <>
                      <button
                        type="button"
                        data-testid={`rules-group-edit-${group.id}`}
                        aria-label={t('office.rules.group.edit')}
                        className="rounded border border-border px-1.5 py-1 text-xs text-text-secondary hover:bg-bg-hover"
                        onClick={() => openEdit(group)}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        data-testid={`rules-group-delete-${group.id}`}
                        aria-label={t('office.rules.group.delete')}
                        className="rounded border border-border px-1.5 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                        disabled={busy}
                        onClick={() => {
                          if (
                            !window.confirm(
                              `${t('office.rules.group.confirmDelete')} (${group.name} · ${group.rules.length} ${t('office.rules.workspace.rulesCount')})`,
                            )
                          )
                            return;
                          void onDelete(group.id);
                        }}
                      >
                        ×
                      </button>
                    </>
                  )}
                </div>
                {active ? (
                  <div className="ml-3 space-y-1">
                    <ul className="space-y-1" data-testid={`rules-group-rules-${group.id}`}>
                      {searchQuery && filteredRules.length === 0 ? (
                        <li>
                          <p className="text-xs text-muted" data-testid="rules-search-empty">
                            {t('office.rules.search.empty')}
                          </p>
                        </li>
                      ) : null}
                      {(searchQuery ? filteredRules : group.rules).map((rule) => (
                        <li key={rule.id}>
                          <button
                            type="button"
                            data-testid={`rule-item-${rule.id}`}
                            aria-current={rule.id === selectedRuleId ? 'true' : undefined}
                            className={`w-full rounded border border-border px-2 py-1 text-left text-xs text-text-secondary hover:bg-bg-hover ${
                              rule.enabled ? '' : 'opacity-50'
                            }`}
                            onClick={() => onSelectRule(rule.id)}
                          >
                            <span className="block font-medium text-text">{rule.name}</span>
                            <span className="block text-muted">
                              {t(`office.rules.type.${rule.type}`)} ·{' '}
                              {t(`office.rules.severity.${rule.severity}`)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      data-testid="rule-create-new"
                      className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
                      onClick={onCreateRule}
                    >
                      {creatingRule
                        ? t('office.rules.detail.cancel')
                        : t('office.rules.detail.newRule')}
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
