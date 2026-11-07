/**
 * 设置页 tab 注册表 —— 导航 / 分组 / 别名 / 类型的唯一事实源（2026-10-28 P2）。
 *
 * 此前 tab 元数据分散在 4 处（`Settings.tsx` 的 tabs 数组、`settingsNavigation`
 * 的 visibleTabs、`settingsPresentation` 的 GROUPS、`settingsSearchIndex` 的
 * 联合类型），新增一个 tab 要同步改 4 处，且已经漂移过（`models` 曾出现在导航
 * 里但类型联合漏过）。本文件把 4 处合并成 1 处：
 *
 * - `key`     → 派生 `SettingsTabKey` 联合类型
 * - `group`   → 派生左侧导航分组与顺序
 * - `aliases` → 派生历史 localStorage 值迁移
 * - `render`  → 内容面板
 *
 * ⚠️ `render` 必须返回 JSX **元素**（`() => <BasicTab />`），不能是
 * `() => BasicTab()`。前者只创建元素、React 正常挂载组件并执行其 hooks；
 * 后者在 render 期间直接调用组件函数，违反 hooks 规则。
 */

import type { TranslationKey } from '../../shared/lib/i18n';
import { EvolutionLog } from '../../widgets/evolution/EvolutionLog';
import { EvolutionPanel } from '../../widgets/evolution/EvolutionPanel';
import { LearnedPreferences } from '../../widgets/evolution/LearnedPreferences';
import { RecallMetrics } from '../../widgets/evolution/RecallMetrics';
import { HarnessDashboard } from '../../widgets/harness/HarnessDashboard';

import { AuditExportTab } from './AuditExportTab';
import { BasicTab } from './BasicTab';
import { FeedbackTab } from './FeedbackTab';
import { GlobalRulesTab } from './GlobalRulesTab';
import { McpTab } from './McpTab';
import { MemorySettingsTab } from './MemorySettingsTab';
import { ModelsServicesTab } from './ModelsServicesTab';
import { NetworkTab } from './NetworkTab';
import { OrchestrationTab } from './OrchestrationTab';
import { PetTab } from './PetTab';
import { PluginsSkillsTab } from './PluginsSkillsTab';
import { RemoteWorkspacesTab } from './RemoteWorkspacesTab';
import { RuntimeEnvTab } from './RuntimeEnvTab';
import { ToolsConnectionsTab } from './ToolsConnectionsTab';
import { UpdatesTab } from './UpdatesTab';
import { UsageStatsTab } from './UsageStatsTab';
import { ZoteroTab } from './ZoteroTab';

export type SettingsTabKey =
  | 'basic'
  | 'models-services'
  | 'orchestration'
  | 'tools-connections'
  | 'mcp'
  | 'plugins-skills'
  | 'global-rules'
<<<<<<< HEAD
=======
  | 'pet'
>>>>>>> origin/main
  | 'memory'
  | 'zotero'
  | 'network'
  | 'remote-workspaces'
  | 'usage-stats'
  | 'updates'
  | 'runtime'
  | 'evolution'
  | 'harness'
<<<<<<< HEAD
  // 2026-10-29: 用户反馈 Tab（管理员转发 + 双向会话，上游 #2669）
  | 'feedback'
  | 'pet'
=======
  // 2026-10-29: 用户反馈 Tab（管理员转发 + 双向会话，上游 #2654）
  | 'feedback'
>>>>>>> origin/main
  | 'audit-export';

export type SettingsGroupId =
  | 'basic'
  | 'models'
  | 'agent'
  | 'knowledge'
  | 'network'
  | 'maintenance'
  | 'advanced'
  | 'feedback';

export interface SettingsGroupDef {
  id: SettingsGroupId;
  zh: string;
  en: string;
}

export interface SettingsTabDef {
  key: SettingsTabKey;
  /** i18n key —— 左侧导航与搜索结果里的 tab 名都用它 */
  labelKey: TranslationKey;
  /** 左侧导航分组 */
  group: SettingsGroupId;
  /** 历史 localStorage 值（旧 tab key）→ 当前 tab */
  aliases?: readonly string[];
  /** 内容面板；返回 JSX 元素而非调用组件 */
  render: () => JSX.Element;
}

/** 分组顺序即左侧导航自上而下的顺序。 */
export const SETTINGS_GROUPS: readonly SettingsGroupDef[] = [
  { id: 'basic', zh: '基础', en: 'Basics' },
  { id: 'models', zh: '模型与服务', en: 'Models and services' },
  { id: 'agent', zh: '智能体', en: 'Agent' },
  { id: 'knowledge', zh: '记忆与知识', en: 'Memory and knowledge' },
  { id: 'network', zh: '网络与远程', en: 'Network and remote' },
  { id: 'maintenance', zh: '使用与维护', en: 'Usage and maintenance' },
  { id: 'advanced', zh: '诊断与实验', en: 'Diagnostics and experiments' },
  { id: 'feedback', zh: '反馈', en: 'Feedback' },
];

export const SETTINGS_TABS: readonly SettingsTabDef[] = [
  {
    key: 'basic',
    labelKey: 'settings.tab.basic',
    group: 'basic',
    // P0-5 起 'general' tab 已下线，迁移表永久保留。
    aliases: ['general'],
    render: () => <BasicTab />,
  },
  {
    key: 'models-services',
    labelKey: 'settings.tab.models-services',
    group: 'models',
    // P1-b: 端点 + 模型 + 更新源合并为单 tab。
    aliases: ['endpoints', 'models', 'providers'],
    render: () => <ModelsServicesTab />,
  },
  {
    key: 'orchestration',
    labelKey: 'settings.tab.orchestration',
    group: 'agent',
    render: () => <OrchestrationTab />,
  },
  {
    key: 'tools-connections',
    labelKey: 'settings.tab.tools-connections',
    group: 'agent',
    render: () => <ToolsConnectionsTab />,
  },
  {
    key: 'mcp',
    labelKey: 'settings.tab.mcp',
    group: 'agent',
    render: () => <McpTab />,
  },
  {
    key: 'plugins-skills',
    labelKey: 'settings.tab.plugins-skills',
    group: 'agent',
    // P1-b: 插件 + 技能合并为单 tab。
    aliases: ['plugins', 'skills'],
    render: () => <PluginsSkillsTab />,
  },
  {
    key: 'global-rules',
    labelKey: 'settings.tab.global-rules',
    group: 'agent',
    render: () => <GlobalRulesTab />,
  },
  {
    key: 'pet',
    labelKey: 'settings.tab.pet',
    group: 'agent',
    // 2026-10-30: 桌面宠物（大肥鱼移植）设置。
    render: () => <PetTab />,
  },
  {
    key: 'memory',
    labelKey: 'settings.tab.memory',
    group: 'knowledge',
    // P1-5: 「记忆与知识」tab 已合并进 memory。
    aliases: ['memory-knowledge'],
    render: () => <MemorySettingsTab />,
  },
  {
    key: 'zotero',
    labelKey: 'settings.tab.zotero',
    group: 'knowledge',
    render: () => <ZoteroTab />,
  },
  {
    key: 'network',
    labelKey: 'settings.tab.network',
    group: 'network',
    render: () => <NetworkTab />,
  },
  {
    key: 'remote-workspaces',
    labelKey: 'settings.tab.remote-workspaces',
    group: 'network',
    render: () => <RemoteWorkspacesTab />,
  },
  {
    key: 'usage-stats',
    labelKey: 'settings.tab.usage-stats',
    group: 'maintenance',
    render: () => <UsageStatsTab />,
  },
  {
    key: 'updates',
    labelKey: 'settings.tab.updates',
    group: 'maintenance',
    render: () => <UpdatesTab />,
  },
  {
    key: 'runtime',
    labelKey: 'settings.tab.runtime',
    group: 'advanced',
    render: () => <RuntimeEnvTab />,
  },
  {
    key: 'evolution',
    labelKey: 'settings.tab.evolution',
    group: 'advanced',
    render: () => (
      <div className="space-y-6">
        <EvolutionPanel />
        <LearnedPreferences />
        <RecallMetrics />
        <EvolutionLog />
      </div>
    ),
  },
  {
    key: 'harness',
    labelKey: 'settings.tab.harness',
    group: 'advanced',
    render: () => <HarnessDashboard />,
  },
  {
    key: 'audit-export',
    labelKey: 'settings.tab.audit-export',
    group: 'advanced',
    // P3: 11 个 tab 的 17 个「复制摘要 / JSON」按钮集中在此。
    render: () => <AuditExportTab />,
  },
  {
    key: 'feedback',
    labelKey: 'settings.tab.feedback',
    group: 'feedback',
    render: () => <FeedbackTab />,
  },
];

export const SETTINGS_TAB_KEYS: readonly SettingsTabKey[] = SETTINGS_TABS.map((tab) => tab.key);

/** 历史持久化值（别名）→ 当前 tab key。 */
export const SETTINGS_TAB_ALIASES: ReadonlyMap<string, SettingsTabKey> = new Map(
  SETTINGS_TABS.flatMap((tab) => (tab.aliases ?? []).map((alias) => [alias, tab.key] as const)),
);

export function findSettingsTab(key: string | null): SettingsTabDef | undefined {
  if (!key) return undefined;
  return SETTINGS_TABS.find((tab) => tab.key === key);
}
