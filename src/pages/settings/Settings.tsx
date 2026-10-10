/**
 * Settings 页面 - 主容器
 *
 * R41/R45 → 2026-09-18 治理：
 * - tab label 收进 i18n（settings.tab.*），不再硬编码中文；
 * - 搜索升级为设置项级：命中具体设置项（settingsSearchIndex），
 *   点击结果跳转到所属 tab；无查询时按 tab 名过滤左侧导航；
 * - 编排 13 项从「通用」拆出为独立「编排」tab。
 */

import { clsx } from 'clsx';
import { Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { ENABLE_UPDATE_PROVIDERS_UI } from '../../shared/updateFeatureFlag';
import { EvolutionLog } from '../../widgets/evolution/EvolutionLog';
import { EvolutionPanel } from '../../widgets/evolution/EvolutionPanel';

import { BasicTab } from './BasicTab';
import { EffectiveSettingsSummary } from './EffectiveSettingsSummary';
import { EndpointsTab } from './EndpointsTab';
import { GeneralTab } from './GeneralTab';
import { McpTab } from './McpTab';
import { MemorySettingsTab } from './MemorySettingsTab';
import { ModelsTab } from './ModelsTab';
import { NetworkTab } from './NetworkTab';
import { OrchestrationTab } from './OrchestrationTab';
import { ProvidersManager } from './ProvidersManager';
import { RemoteWorkspacesTab } from './RemoteWorkspacesTab';
import { RuntimeEnvTab } from './RuntimeEnvTab';
import { ToolsConnectionsTab } from './ToolsConnectionsTab';
import { UpdatesTab } from './UpdatesTab';
import { UsageStatsTab } from './UsageStatsTab';
import { ZoteroTab } from './ZoteroTab';
import { initialSettingsTab } from './settingsNavigation';
import { focusSettingsEntry, settingsGroups } from './settingsPresentation';
import {
  searchSettings,
  type SettingsSearchEntry,
  type SettingsTabKey,
} from './settingsSearchIndex';

export type SettingsTab = SettingsTabKey;

/**
 * 历史持久化 tab 值 → 当前 tab 的迁移表。
 *
 * - `general`：P0-5 之前 'general' 不在 tabs 列表里却承载默认落地页，迁到 basic。
 * - `memory-knowledge`：P1-5 把两个「记忆」tab 合并成一个，该 key 已下线，
 *   迁到 memory。老用户 localStorage 里还留着旧值，不迁移就会落进
 *   “无 tab 内容”的空白页。
 */
const LEGACY_TAB_ALIASES: Record<string, SettingsTab> = {
  general: 'basic',
  'memory-knowledge': 'memory',
};

function migrateTab(saved: string): SettingsTab {
  return (LEGACY_TAB_ALIASES[saved] ?? saved) as SettingsTab;
}

export function Settings() {
  // R45: 记住上次访问的 tab —— localStorage 持久化，重开设置页恢复
  const [activeTab, setActiveTabState] = useState<SettingsTab>(() => {
    try {
      const saved = localStorage.getItem('sage:settings-tab');
      // 上游把「记忆与知识」tab 重命名为 memory：旧书签先按上游别名迁移，
      // 再走 initialSettingsTab 的合法性与可见性校验（providers 开关、未知值回退 basic）。
      return initialSettingsTab(saved ? migrateTab(saved) : null, ENABLE_UPDATE_PROVIDERS_UI());
    } catch {
      /* ignore */
    }
    return 'basic';
  });
  const setActiveTab = useCallback((tab: SettingsTab) => {
    setActiveTabState(tab);
    try {
      localStorage.setItem('sage:settings-tab', tab);
    } catch {
      /* ignore */
    }
  }, []);
  const [searchQuery, setSearchQuery] = useState('');
  const contentRef = useRef<HTMLDivElement>(null);
  // 上游 P1-4：待定位的设置项锚点。点击搜索结果时写入，在目标 tab 渲染完成后
  // 消费一次。用 ref 而非 state —— 它不是渲染输入，只是一条「下一帧要做的事」。
  const pendingAnchorRef = useRef<{ key: string; entry: SettingsSearchEntry } | null>(null);
  // 每次点击搜索结果自增，驱动锚点定位 effect（不能用 activeTab：见 jumpToItem）。
  const [jumpToken, setJumpToken] = useState(0);
  // 条目未登记 data-settings-anchor 时，退回「按标签文本在容器内定位」；
  // 两条路都定不到就如实提示，不伪造跳转。
  const [fallbackEntry, setFallbackEntry] = useState<SettingsSearchEntry | null>(null);
  const [focusMissing, setFocusMissing] = useState(false);
  const { settings, updateSettings, resetSettings } = useSettings();
  const { t, locale } = useI18n();

  const tabs: { key: SettingsTab; label: string }[] = [
    // P0-5: 'general' 此前不在此列表（却作为默认 activeTab + 承载破坏性
    // 「重置全部设置」），导致默认落地页在左侧导航无高亮项、切走后无法
    // 返回。SettingsTabKey 与 i18n 均已有该 key，属单纯的数组漏项。
    { key: 'general', label: t('settings.tab.general') },
    { key: 'basic', label: t('settings.tab.basic') },
    { key: 'tools-connections', label: t('settings.tab.tools-connections') },
    { key: 'endpoints', label: t('settings.tab.endpoints') },
    { key: 'models', label: t('settings.tab.models') },
    { key: 'orchestration', label: t('settings.tab.orchestration') },
    // P1-5: 「记忆与知识」tab 已下线并入这里 —— 它里面没有任何知识库设置，
    // 却让用户以为记忆与知识是绑定的，徒增记忆能力的入口数量。
    { key: 'memory', label: t('settings.tab.memory') },
    { key: 'network', label: t('settings.tab.network') },
    { key: 'mcp', label: t('settings.tab.mcp') },
    { key: 'remote-workspaces', label: t('settings.tab.remote-workspaces') },
    { key: 'zotero', label: t('settings.tab.zotero') },
    { key: 'runtime', label: t('settings.tab.runtime') },
    { key: 'evolution', label: t('settings.tab.evolution') },
    { key: 'updates', label: t('settings.tab.updates') },
    { key: 'usage-stats', label: t('settings.tab.usage-stats' as TranslationKey) },
  ];
  if (ENABLE_UPDATE_PROVIDERS_UI()) {
    tabs.push({ key: 'providers', label: t('settings.tab.providers' as TranslationKey) });
  }

  // 设置项级搜索：命中项列表 + 其所属 tab（导航区仍按 tab 名过滤）
  const matchedItems = useMemo(() => searchSettings(searchQuery), [searchQuery]);
  const matchingTabs = useMemo(() => new Set(matchedItems.map((item) => item.tab)), [matchedItems]);
  const query = searchQuery.trim().toLowerCase();
  const filteredTabs = query
    ? tabs.filter((tab) => matchingTabs.has(tab.key) || tab.label.toLowerCase().includes(query))
    : tabs;

  const jumpToItem = (item: SettingsSearchEntry): void => {
    setActiveTab(item.tab);
    setSearchQuery('');
    setFocusMissing(false);
    // 先按上游的 data-settings-anchor 定位（登记过锚点的条目走这条路）。
    pendingAnchorRef.current = { key: item.key, entry: item };
    // 用自增 token 触发定位，而不是依赖 [activeTab] —— 命中项就在当前 tab 时
    // activeTab 不变，effect 不会重跑，定位会被静默吞掉。
    setJumpToken((n) => n + 1);
  };

  // 上游 P1-4：目标 tab 渲染完成后消费锚点 —— 滚动到该行并短暂高亮。
  // 走 setTimeout(0) 而非直接在 effect 里查：目标行属于刚刚挂载的子树，
  // effect 执行时 DOM 尚未可用，下一帧才稳定。
  useEffect(() => {
    const pending = pendingAnchorRef.current;
    if (!pending) return;
    pendingAnchorRef.current = null;
    const handle = window.setTimeout(() => {
      const selector = `[data-settings-anchor="${CSS.escape(pending.key)}"]`;
      const target = document.querySelector(selector);
      if (target) {
        // scrollIntoView 在 jsdom 中未实现 —— 必须守卫，否则测试环境直接抛错。
        if (typeof target.scrollIntoView === 'function') {
          target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        target.classList.add('settings-anchor-flash');
        window.setTimeout(() => target.classList.remove('settings-anchor-flash'), 2000);
        return;
      }
      // 未登记锚点 → 退回本分支的「按标签文本定位」兜底，仍定不到再如实提示。
      setFallbackEntry(pending.entry);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [jumpToken]);

  useEffect(() => {
    const container = contentRef.current;
    if (!container || !fallbackEntry) return;
    const attempt = () => {
      if (!focusSettingsEntry(container, fallbackEntry)) return false;
      setFallbackEntry(null);
      return true;
    };
    if (attempt()) return;
    const observer = new MutationObserver(attempt);
    observer.observe(container, { childList: true, subtree: true });
    const timer = window.setTimeout(() => {
      observer.disconnect();
      setFocusMissing(true);
      setFallbackEntry(null);
    }, 2000);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [activeTab, fallbackEntry]);
  const groups = settingsGroups(
    filteredTabs.map((tab) => tab.key),
    locale,
  );

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left sub-nav (U15 from OpenWorker) */}
      <div className="w-52 border-r border-line bg-bg-muted flex-shrink-0 flex flex-col">
        <div className="h-12 flex items-center px-4 border-b border-line">
          <h2 className="text-ui-lg font-semibold text-ink">{t('settings.title')}</h2>
        </div>
        <div className="px-2 pt-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              data-testid="settings-search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('settings.search.placeholder')}
              className="w-full pl-7 pr-6 py-1.5 text-ui-sm rounded-md border border-border bg-bg text-text placeholder:text-muted"
            />
            {searchQuery && (
              <button
                type="button"
                data-testid="settings-search-clear"
                aria-label="清空搜索"
                onClick={() => setSearchQuery('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-muted hover:text-text hover:bg-bg-hover"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        </div>
        {query && (
          <div className="px-2 pt-2 max-h-64 overflow-y-auto" data-testid="settings-search-results">
            <div className="px-2 pb-1 text-ui-xs text-muted">
              {t('settings.search.hits').replace('{count}', String(matchedItems.length))}
            </div>
            {matchedItems.map((item) => (
              <button
                key={item.key}
                type="button"
                data-testid={`settings-search-item-${item.key}`}
                className="w-full px-2 py-1.5 text-left rounded-md hover:bg-bg-hover"
                onClick={() => jumpToItem(item)}
              >
                <div className="text-xs text-ink leading-snug">
                  {locale === 'en' ? item.labelEn : item.label}
                </div>
                <div className="text-ui-xs text-muted">
                  {tabs.find((tab) => tab.key === item.tab)?.label}
                </div>
              </button>
            ))}
            {matchedItems.length === 0 && (
              <div className="px-2 py-1 text-xs text-muted">{t('settings.search.empty')}</div>
            )}
          </div>
        )}
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {groups.map((group) => {
            const selected = group.keys.includes(activeTab);
            return (
              <section key={group.id}>
                <button
                  type="button"
                  data-testid={`settings-group-${group.id}`}
                  aria-expanded={selected}
                  onClick={() => setActiveTab(group.keys[0])}
                  className={`w-full px-3 py-2 text-ui-base rounded text-left ${selected ? 'bg-primary/10 text-primary font-medium' : 'text-muted hover:bg-bg-hover'}`}
                >
                  {group.label}
                </button>
                {(selected || query) &&
                  group.keys.length > 1 &&
                  group.keys.map((key) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setActiveTab(key)}
                      className={clsx(
                        'w-full pl-5 pr-2 py-1.5 text-ui-sm rounded-r text-left transition-colors',
                        activeTab === key
                          ? 'border-l-2 border-primary bg-primary/5 text-primary font-medium'
                          : 'text-muted hover:bg-bg-hover',
                      )}
                    >
                      {tabs.find((tab) => tab.key === key)?.label}
                    </button>
                  ))}
              </section>
            );
          })}
        </nav>
      </div>

      {/* Right content panel */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto" ref={contentRef}>
            <EffectiveSettingsSummary />
            {focusMissing && (
              <p role="status" className="text-ui-sm text-warning mb-2">
                {locale === 'en'
                  ? 'The section is open, but the exact setting is unavailable or hidden by an advanced option.'
                  : '已打开所属分组；该设置可能尚未加载或需展开高级选项，未伪造定位结果。'}
              </p>
            )}
            {activeTab === 'general' && <GeneralTab resetSettings={resetSettings} />}
            {activeTab === 'basic' && <BasicTab />}
            {activeTab === 'tools-connections' && <ToolsConnectionsTab />}
            {activeTab === 'endpoints' && (
              <EndpointsTab settings={settings} updateSettings={updateSettings} />
            )}
            {activeTab === 'models' && (
              <ModelsTab settings={settings} updateSettings={updateSettings} />
            )}
            {activeTab === 'orchestration' && <OrchestrationTab />}
            {/* P1-5: 记忆设置合并为单 tab（日常开关 + 记忆引擎），顶部指向
                唯一的记忆工作台 /memory —— 设置页不再自成第三个记忆入口。 */}
            {activeTab === 'memory' && <MemorySettingsTab />}
            {activeTab === 'network' && <NetworkTab />}
            {activeTab === 'remote-workspaces' && <RemoteWorkspacesTab />}
            {activeTab === 'mcp' && <McpTab />}
            {activeTab === 'zotero' && <ZoteroTab />}
            {activeTab === 'runtime' && <RuntimeEnvTab />}
            {activeTab === 'evolution' && (
              <div className="space-y-6">
                <EvolutionPanel />
                <EvolutionLog />
              </div>
            )}
            {activeTab === 'updates' && <UpdatesTab />}
            {activeTab === 'usage-stats' && <UsageStatsTab />}
            {activeTab === 'providers' && ENABLE_UPDATE_PROVIDERS_UI() && <ProvidersManager />}
          </div>
        </div>
      </div>
    </div>
  );
}
