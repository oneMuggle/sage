/** Rules-center dictionary — English. */
import type { RulesTranslationKey } from '../zh/rules';

export const enRules: Record<RulesTranslationKey, string> = {
  'rules.title': 'Rules center',
  'rules.subtitle':
    'Project rules, playbook requirements, project charter and global rules live here; edit each rule from its own source.',
  'rules.search.placeholder': 'Search rule content, category or source',
  'rules.filter.all': 'All',
  'rules.layer.constraint': 'Project rules',
  'rules.layer.playbook': 'Playbook',
  'rules.layer.doc': 'Project charter',
  'rules.layer.global': 'Global rules',
  'rules.health.enabled': '{count} enabled rules',
  'rules.health.conflicts': '{count} conflicts',
  'rules.health.healthy': 'No conflicts',
  'rules.action.refresh': 'Refresh',
  'rules.action.retry': 'Retry',
  'rules.action.openEffective': 'View effective rules',
  'rules.action.close': 'Close',
  'rules.loading': 'Loading rules…',
  'rules.loadFailed': 'Failed to load rules: {message}',
  'rules.empty.title': 'No rules for this project yet',
  'rules.empty.hint':
    'A later version lets you create rules here or have AI draft them from the project state.',
  'rules.empty.filtered': 'No rules match the current filters',
  'rules.row.conflict': 'Conflict hint',
  'rules.row.readonly': 'Read-only',
  'rules.row.trigger': 'Trigger: {trigger}',
  'rules.row.priority': 'Priority {priority}',
  'rules.row.enabled': 'Enabled',
  'rules.row.disabled': 'Disabled',
  'rules.row.openSource': 'Open source',
  'rules.drawer.title': 'Effective rules',
  'rules.drawer.description':
    'Listed in AI injection order; rules sharing a category with overlapping triggers are flagged, never merged.',
  'rules.drawer.empty': 'No effective rules',
  'rules.drawer.order':
    'Injection order: global rules → project charter → project rules → current-stage playbook → content checks',
  'rules.drawer.checkLabel': 'Content check',
};
