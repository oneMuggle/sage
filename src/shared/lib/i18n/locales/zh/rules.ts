/** 规则中心词典 — 中文（默认）。 */
export const zhRules = {
  'rules.title': '规则中心',
  'rules.subtitle':
    '项目规则、规程要求、项目总纲与全局规则集中在这里，改动规则请从对应来源进入。',
  'rules.search.placeholder': '搜索规则内容、分类或来源',
  'rules.filter.all': '全部',
  'rules.layer.constraint': '项目规则',
  'rules.layer.playbook': '规程',
  'rules.layer.doc': '项目总纲',
  'rules.layer.global': '全局规则',
  'rules.health.enabled': '{count} 条启用规则',
  'rules.health.conflicts': '{count} 个冲突',
  'rules.health.healthy': '无冲突',
  'rules.action.refresh': '刷新',
  'rules.action.retry': '重试',
  'rules.action.openEffective': '查看最终生效规则',
  'rules.action.close': '关闭',
  'rules.loading': '正在加载规则…',
  'rules.loadFailed': '规则加载失败：{message}',
  'rules.empty.title': '该项目还没有规则',
  'rules.empty.hint': '在后续版本中可以直接新建规则，或让 AI 根据项目现状生成。',
  'rules.empty.filtered': '没有符合筛选条件的规则',
  'rules.row.conflict': '冲突提示',
  'rules.row.readonly': '只读',
  'rules.row.trigger': '触发：{trigger}',
  'rules.row.priority': '优先级 {priority}',
  'rules.row.enabled': '启用中',
  'rules.row.disabled': '已停用',
  'rules.row.openSource': '查看来源',
  'rules.drawer.title': '最终生效规则',
  'rules.drawer.description':
    '按 AI 注入顺序排列；同分类且触发词重叠时只提示冲突，不会自动合并。',
  'rules.drawer.empty': '暂无生效规则',
  'rules.drawer.order':
    '注入顺序：全局规则 → 项目总纲 → 项目规则 → 当前阶段规程 → 内容检查',
  'rules.drawer.checkLabel': '内容检查',
} as const;

export type RulesTranslationKey = keyof typeof zhRules;
