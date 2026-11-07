/**
 * 规则中心视图纯函数。
 *
 * 分层顺序与 backend/services/rules_registry.py 的 LAYER_ORDER 一致：
 * 全局 → 项目总纲 → 项目规则 → 规程（含内容检查）。
 */
import type { RuleConflict, RuleEntry, RuleLayer } from '../../shared/api/rulesApi';
import type { TranslationKey } from '../../shared/lib/i18n';

export const LAYER_ORDER: readonly RuleLayer[] = ['global', 'doc', 'constraint', 'playbook'];

export type LayerFilter = RuleLayer | 'all';

export interface RuleGroup {
  layer: RuleLayer;
  entries: RuleEntry[];
}

const LABEL_KEYS: Record<LayerFilter, TranslationKey> = {
  all: 'rules.filter.all',
  constraint: 'rules.layer.constraint',
  playbook: 'rules.layer.playbook',
  doc: 'rules.layer.doc',
  global: 'rules.layer.global',
};

export function layerLabelKey(layer: LayerFilter): TranslationKey {
  return LABEL_KEYS[layer];
}

/** 按层级分组；空层不产生分组，组内保持后端顺序。 */
export function buildRuleGroups(entries: readonly RuleEntry[]): RuleGroup[] {
  return LAYER_ORDER.map((layer) => ({
    layer,
    entries: entries.filter((entry) => entry.layer === layer),
  })).filter((group) => group.entries.length > 0);
}

export interface RuleFilterOptions {
  search: string;
  layer: LayerFilter;
}

export function filterRules(
  entries: readonly RuleEntry[],
  options: RuleFilterOptions,
): RuleEntry[] {
  const needle = options.search.trim().toLowerCase();
  return entries.filter((entry) => {
    if (options.layer !== 'all' && entry.layer !== options.layer) return false;
    if (!needle) return true;
    return [entry.content, entry.category, entry.sourceLabel, entry.scope].some((value) =>
      value.toLowerCase().includes(needle),
    );
  });
}

export function countEnabled(entries: readonly RuleEntry[]): number {
  return entries.filter((entry) => entry.enabled).length;
}

export function conflictedRuleIds(conflicts: readonly RuleConflict[]): Set<string> {
  const ids = new Set<string>();
  for (const conflict of conflicts) {
    ids.add(conflict.a);
    ids.add(conflict.b);
  }
  return ids;
}

/** 注入顺序；同一层内「内容检查」（id 含 `:check:`）排在该阶段普通规则之后。 */
export function sortEffectiveRules(entries: readonly RuleEntry[]): RuleEntry[] {
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => {
      const layerDiff =
        LAYER_ORDER.indexOf(left.entry.layer) - LAYER_ORDER.indexOf(right.entry.layer);
      if (layerDiff !== 0) return layerDiff;
      const checkDiff =
        Number(left.entry.id.includes(':check:')) - Number(right.entry.id.includes(':check:'));
      return checkDiff !== 0 ? checkDiff : left.index - right.index;
    })
    .map(({ entry }) => entry);
}
