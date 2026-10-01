// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { Settings } from '../Settings';

// 各 tab 组件一律替换为带锚点的占位：P1-4 关心的是「切 tab → 定位 → 高亮」
// 这条链路，与各 tab 内部真实控件无关。真实控件的锚点由 components.test.tsx
// 与各 tab 自己的测试覆盖。
vi.mock('../useSettings', () => ({ useSettings: () => ({ settings: {}, updateSettings: vi.fn(), resetSettings: vi.fn() }) }));
vi.mock('../BasicTab', () => ({ BasicTab: () => <div data-testid="tab-basic" /> }));
vi.mock('../EffectiveSettingsSummary', () => ({ EffectiveSettingsSummary: () => <div /> }));
vi.mock('../EndpointsTab', () => ({ EndpointsTab: () => <div data-testid="tab-endpoints" /> }));
vi.mock('../GeneralTab', () => ({
  GeneralTab: () => (
    <div data-testid="tab-general">
      <div data-settings-anchor="reset_settings">重置全部设置</div>
    </div>
  ),
}));
vi.mock('../McpTab', () => ({ McpTab: () => <div data-testid="tab-mcp" /> }));
vi.mock('../MemorySettingsTab', () => ({
  MemorySettingsTab: () => (
    <div data-testid="tab-memory">
      <div data-settings-anchor="autoMemory">自动记忆提取</div>
      <a href="/memory" data-testid="memory-workspace-link">打开记忆页面</a>
    </div>
  ),
}));
vi.mock('../ModelsTab', () => ({
  ModelsTab: () => (
    <div data-testid="tab-models">
      <div data-settings-anchor="temperature">Temperature</div>
    </div>
  ),
}));
vi.mock('../NetworkTab', () => ({ NetworkTab: () => <div data-testid="tab-network" /> }));
vi.mock('../OrchestrationTab', () => ({
  OrchestrationTab: () => (
    <div data-testid="tab-orchestration">
      <div data-settings-anchor="orch.runTokenBudget">Run token 预算</div>
    </div>
  ),
}));
vi.mock('../ProvidersManager', () => ({ ProvidersManager: () => <div data-testid="tab-providers" /> }));
vi.mock('../RemoteWorkspacesTab', () => ({ RemoteWorkspacesTab: () => <div data-testid="tab-remote-workspaces" /> }));
vi.mock('../RuntimeEnvTab', () => ({ RuntimeEnvTab: () => <div data-testid="tab-runtime" /> }));
vi.mock('../ToolsConnectionsTab', () => ({ ToolsConnectionsTab: () => <div data-testid="tab-tools-connections" /> }));
vi.mock('../UpdatesTab', () => ({ UpdatesTab: () => <div data-testid="tab-updates" /> }));
vi.mock('../UsageStatsTab', () => ({ UsageStatsTab: () => <div data-testid="tab-usage-stats" /> }));
vi.mock('../ZoteroTab', () => ({ ZoteroTab: () => <div data-testid="tab-zotero" /> }));
vi.mock('../../../widgets/evolution/EvolutionPanel', () => ({ EvolutionPanel: () => <div /> }));
vi.mock('../../../widgets/evolution/EvolutionLog', () => ({ EvolutionLog: () => <div /> }));
vi.mock('../../../shared/updateFeatureFlag', () => ({ ENABLE_UPDATE_PROVIDERS_UI: () => true }));

function renderSettings() {
  return render(
    <I18nProvider defaultLocale="zh">
      <Settings />
    </I18nProvider>,
  );
}

/** 点击搜索结果并等定位链路（effect + setTimeout）跑完。 */
async function clickSearchResult(key: string) {
  await act(async () => {
    fireEvent.change(screen.getByTestId('settings-search'), { target: { value: key } });
  });
  const result = await screen.findByTestId(`settings-search-item-${key}`);
  await act(async () => {
    fireEvent.click(result);
  });
}

/** 等目标行被高亮（定位走 effect → setTimeout(0) → 加 class）。 */
async function waitForFlash(anchor: string) {
  return waitFor(() => {
    const el = document.querySelector(`[data-settings-anchor="${anchor}"]`);
    expect(el).not.toBeNull();
    expect(el?.classList.contains('settings-anchor-flash')).toBe(true);
  });
}

beforeEach(() => {
  localStorage.clear();
  vi.useRealTimers();
});

describe('设置搜索锚点定位 (P1-4)', () => {
  it('switches to the owning tab and highlights the anchored row', async () => {
    renderSettings();
    // 默认落在 general tab；搜索「重置全部设置」应跳到 general 并高亮该行。
    // 注意这条同时守住了「命中项就在当前 tab」的场景 —— 此时 activeTab 不变，
    // 定位不能被依赖 activeTab 的 effect 静默吞掉。
    await clickSearchResult('reset_settings');
    await waitForFlash('reset_settings');
  });

  it('scrolls the anchored row into view without throwing', async () => {
    // jsdom 未实现 scrollIntoView（Element.prototype 上不存在）——定位逻辑
    // 必须守卫而不是直接抛错，否则整个设置页在测试/降级环境里会崩。
    renderSettings();
    const scrollIntoView = vi.fn();
    (Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView = scrollIntoView;
    try {
      await clickSearchResult('reset_settings');
      await waitForFlash('reset_settings');
      expect(scrollIntoView).toHaveBeenCalled();
    } finally {
      delete (Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it('crosses tabs: an entry in another tab still lands on the right row', async () => {
    renderSettings();
    await clickSearchResult('orch.runTokenBudget');
    expect(screen.getByTestId('tab-orchestration')).toBeInTheDocument();
    await waitForFlash('orch.runTokenBudget');
  });

  it('falls back to plain tab switching when the entry has no anchor', async () => {
    // 整 tab 级条目（端点管理、MCP…）本身没有对应行 —— 必须静默降级为
    // 「只切 tab」，不报错、不空手。
    renderSettings();
    await clickSearchResult('endpoints');
    expect(screen.getByTestId('tab-endpoints')).toBeInTheDocument();
  });

  it('clears the search box after jumping', async () => {
    renderSettings();
    await clickSearchResult('reset_settings');
    expect(screen.getByTestId('settings-search')).toHaveValue('');
  });
});

describe('记忆 tab 合并 (P1-5)', () => {
  it('只存在一个记忆 tab —— 不再有「记忆与知识」', () => {
    renderSettings();
    // IA1/IA2 的可执行判据：左侧导航里「记忆」只出现一次。
    const navButtons = screen.getAllByRole('button');
    const memoryLabels = navButtons
      .map((b) => b.textContent?.trim())
      .filter((label) => label === '记忆');
    expect(memoryLabels).toHaveLength(1);
    expect(navButtons.some((b) => b.textContent?.includes('记忆与知识'))).toBe(false);
  });

  it('旧用户持久化的 memory-knowledge 自动迁到 memory，不落空白页', () => {
    // 老用户 localStorage 里还留着 'memory-knowledge'。不迁移的话 activeTab
    // 会指向一个已下线的 tab —— 左侧无高亮项、右侧一片空白，且用户不知道
    // 该点哪里才能回去。这是最典型的静默失败。
    localStorage.setItem('sage:settings-tab', 'memory-knowledge');
    renderSettings();
    expect(screen.getByTestId('tab-memory')).toBeInTheDocument();
  });

  it('记忆 tab 指向唯一的记忆工作台 /memory', () => {
    // 收敛的第二半：设置页负责「怎么配」，内容归 /memory 页管。
    localStorage.setItem('sage:settings-tab', 'memory');
    renderSettings();
    const link = screen.getByTestId('memory-workspace-link');
    expect(link.getAttribute('href')).toBe('/memory');
  });
});
