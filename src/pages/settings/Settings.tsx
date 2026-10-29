/**
 * Settings 页面 - 主容器
 *
 * R41/R45 → 2026-09-18 治理：
 * - tab label 收进 i18n（settings.tab.*），不再硬编码中文；
 * - 搜索升级为设置项级：命中具体设置项（settingsSearchIndex），
 *   点击结果跳转到所属 tab；无查询时按 tab 名过滤左侧导航；
 * - 编排 13 项从「通用」拆出为独立「编排」tab。
 *
 * P2 (2026-10-28)：tab 元数据（key / label / 分组 / 别名 / 内容面板）
 * 全部收进 `settingsTabs.tsx` 注册表，本文件只负责搜索、锚点定位与渲染。
 * 新增 tab 只改注册表 1 处。
 */

import { clsx } from 'clsx';
import { Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { EffectiveSettingsSummary } from './EffectiveSettingsSummary';
import { initialSettingsTab } from './settingsNavigation';
import { focusSettingsEntry, settingsGroups } from './settingsPresentation';
import { searchSettings, type SettingsSearchEntry } from './settingsSearchIndex';
import { SETTINGS_TABS, findSettingsTab, type SettingsTabKey } from './settingsTabs';

export type SettingsTab = SettingsTabKey;

export function Settings() {
  // R45: 记住上次访问的 tab —— localStorage 持久化，重开设置页恢复
  const [activeTab, setActiveTabState] = useState<SettingsTab>(() => {
    try {
      const saved = localStorage.getItem('sage:settings-tab');
      // 历史 localStorage 值（旧 tab key、已下线 tab）由 initialSettingsTab
      // 统一做别名迁移 + 合法性校验，未知值回退 basic。
      return initialSettingsTab(saved);
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
  const { t, locale } = useI18n();

  // 左侧导航与搜索结果里的 tab 名都来自注册表。
  const tabs = useMemo(
    () => SETTINGS_TABS.map((tab) => ({ key: tab.key, label: t(tab.labelKey) })),
    [t],
  );

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

  // 内容面板由注册表决定 —— render 返回 JSX 元素，React 正常挂载组件。
  const activeTabDef = useMemo(() => findSettingsTab(activeTab), [activeTab]);

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
        <nav className="flex-1 overflow-y-auto p-2 space-y-3">
          {groups.map((group) => (
            <section key={group.id}>
              <div
                data-testid={`settings-group-${group.id}`}
                className="px-3 py-1 text-ui-2xs font-medium text-muted uppercase tracking-wide"
              >
                {group.label}
              </div>
              <div className="mt-0.5 space-y-0.5">
                {group.keys.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setActiveTab(key)}
                    className={clsx(
                      'w-full px-3 py-1.5 text-ui-sm rounded text-left transition-colors',
                      activeTab === key
                        ? 'bg-primary/10 text-primary font-medium'
                        : 'text-text-secondary hover:bg-bg-hover',
                    )}
                  >
                    {tabs.find((tab) => tab.key === key)?.label}
                  </button>
                ))}
              </div>
            </section>
          ))}
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
            {activeTabDef?.render()}
          </div>
        </div>
      </div>
    </div>
  );
}
