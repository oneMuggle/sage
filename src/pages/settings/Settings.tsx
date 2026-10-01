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
import { Search } from 'lucide-react';
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
import { MemoryKnowledgeTab } from './MemoryKnowledgeTab';
import { MemoryTab } from './MemoryTab';
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

export function Settings() {
  // R45: 记住上次访问的 tab —— localStorage 持久化，重开设置页恢复
  const [activeTab, setActiveTabState] = useState<SettingsTab>(() => {
    try {
      const saved = localStorage.getItem('sage:settings-tab');
      return initialSettingsTab(saved, ENABLE_UPDATE_PROVIDERS_UI());
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
  const [focusEntry, setFocusEntry] = useState<SettingsSearchEntry | null>(null);
  const [focusMissing, setFocusMissing] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const { settings, updateSettings, resetSettings } = useSettings();
  const { t, locale } = useI18n();

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'basic', label: t('settings.tab.basic') },
    { key: 'memory-knowledge', label: t('settings.tab.memory-knowledge') },
    { key: 'tools-connections', label: t('settings.tab.tools-connections') },
    { key: 'endpoints', label: t('settings.tab.endpoints') },
    { key: 'models', label: t('settings.tab.models') },
    { key: 'orchestration', label: t('settings.tab.orchestration') },
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
    setFocusEntry(item);
  };

  useEffect(() => {
    const container = contentRef.current;
    if (!container || !focusEntry) return;
    const attempt = () => {
      if (!focusSettingsEntry(container, focusEntry)) return false;
      setFocusEntry(null);
      return true;
    };
    if (attempt()) return;
    const observer = new MutationObserver(attempt);
    observer.observe(container, { childList: true, subtree: true });
    const timer = window.setTimeout(() => {
      observer.disconnect();
      setFocusMissing(true);
      setFocusEntry(null);
    }, 2000);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [activeTab, focusEntry]);
  const groups = settingsGroups(
    filteredTabs.map((tab) => tab.key),
    locale,
  );

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left sub-nav (U15 from OpenWorker) */}
      <div className="w-52 border-r border-line bg-bg-muted flex-shrink-0 flex flex-col">
        <div className="h-12 flex items-center px-4 border-b border-line">
          <h2 className="text-[16px] font-semibold text-ink">{t('settings.title')}</h2>
        </div>
        <div className="px-2 pt-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              data-testid="settings-search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('settings.search.placeholder')}
              className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-border bg-bg text-text placeholder:text-muted"
            />
          </div>
        </div>
        {query && (
          <div className="px-2 pt-2 max-h-64 overflow-y-auto" data-testid="settings-search-results">
            <div className="px-2 pb-1 text-[10px] text-muted">
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
                <div className="text-[10px] text-muted">
                  {tabs.find((tab) => tab.key === item.tab)?.label}
                </div>
              </button>
            ))}
            {matchedItems.length === 0 && (
              <div className="px-2 py-1 text-xs text-muted">{t('settings.search.empty')}</div>
            )}
          </div>
        )}
        <nav className="p-2 space-y-1">
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
                        'w-full pl-5 pr-2 py-2 text-ui-sm rounded text-left',
                        activeTab === key
                          ? 'text-primary font-medium'
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
            {activeTab === 'memory-knowledge' && <MemoryKnowledgeTab />}
            {activeTab === 'tools-connections' && <ToolsConnectionsTab />}
            {activeTab === 'endpoints' && (
              <EndpointsTab settings={settings} updateSettings={updateSettings} />
            )}
            {activeTab === 'models' && (
              <ModelsTab settings={settings} updateSettings={updateSettings} />
            )}
            {activeTab === 'orchestration' && <OrchestrationTab />}
            {activeTab === 'memory' && <MemoryTab />}
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
