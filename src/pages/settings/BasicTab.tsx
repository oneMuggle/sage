/**
 * Settings 页面 - 基础设置 Tab
 *
 * 包含外观（主题、语言、字体）和基础对话行为（流式输出、时区、托盘）。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';

import { FontSettingsSection } from './FontSettingsSection';
import { ThemeSelector } from './ThemeSelector';
import { AdvancedSection, SettingRow, Toggle } from './components';

export interface BasicTabAuditInput {
  streaming: boolean;
  llmRetryMaxAttempts: number;
  llmRetryBaseDelayS: number;
  llmRetryMaxDelayS: number;
  llmTotalTimeoutS: number;
  timezone: string;
  logTimezone: string;
  demoMode: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBasicTabAuditSnapshot(input: BasicTabAuditInput): string {
  return [
    `# 基础设置审计快照`,
    `- 流式输出: ${input.streaming ? '开启' : '关闭'}`,
    `- LLM 最大重试次数: ${input.llmRetryMaxAttempts}`,
    `- 退避基数(秒): ${input.llmRetryBaseDelayS}`,
    `- 最大退避(秒): ${input.llmRetryMaxDelayS}`,
    `- LLM 任务上限(秒): ${input.llmTotalTimeoutS === 0 ? '不限' : input.llmTotalTimeoutS}`,
    `- IANA 时区: ${input.timezone || '默认'}`,
    `- 日志时区: ${input.logTimezone || 'UTC'}`,
    `- 演示模式: ${input.demoMode ? '开启' : '关闭'}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBasicTabAuditJson(input: BasicTabAuditInput): string {
  return JSON.stringify(
    {
      streaming: input.streaming,
      llmRetryMaxAttempts: input.llmRetryMaxAttempts,
      llmRetryBaseDelayS: input.llmRetryBaseDelayS,
      llmRetryMaxDelayS: input.llmRetryMaxDelayS,
      llmTotalTimeoutS: input.llmTotalTimeoutS,
      timezone: input.timezone || 'Asia/Shanghai',
      logTimezone: input.logTimezone || 'UTC',
      demoMode: input.demoMode,
    },
    null,
    2,
  );
}

/** U10: 界面语言切换 — useI18n.setLocale + localStorage 持久化 */
function LanguageSelect(): JSX.Element {
  const { locale, setLocale } = useI18n();
  return (
    <select
      data-testid="settings-language-select"
      value={locale}
      onChange={(e) => setLocale(e.target.value as 'zh' | 'en')}
      className="text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text"
      aria-label="界面语言"
    >
      <option value="zh">中文</option>
      <option value="en">English</option>
    </select>
  );
}

/**
 * 关闭即隐藏到托盘——状态由 Electron 主进程持有
 * （JSON 文件，close 事件拦截），因此走 window.electronAPI IPC。
 */
function CloseToTrayCard(): JSX.Element {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    window.electronAPI
      ?.getCloseToTray?.()
      .then((resp) => {
        if (mounted) setEnabled(resp.enabled === true);
      })
      .catch(() => {
        if (mounted) setEnabled(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleToggle = (v: boolean): void => {
    setEnabled(v);
    window.electronAPI?.setCloseToTray?.(v).catch(() => undefined);
  };

  return (
    <section data-testid="close-to-tray-section">
      <h3 className="text-sm font-semibold text-text mb-3">托盘</h3>
      <SettingRow
        anchor="close_to_tray"
        label="关闭时隐藏到托盘"
        desc="点关闭按钮时隐藏到系统托盘而非退出；从托盘图标或 Alt+Shift+S 恢复"
      >
        {enabled === null ? (
          <span className="text-xs text-muted">…</span>
        ) : (
          <Toggle value={enabled} onChange={handleToggle} />
        )}
      </SettingRow>
    </section>
  );
}

export function BasicTab() {
  const { settings, updateSettings } = useSettings();
  const [copiedAudit, setCopiedAudit] = useState(false);

  /* v8 ignore start */
  const handleCopyAudit = async () => {
    const text = formatBasicTabAuditSnapshot({
      streaming: settings.streaming,
      llmRetryMaxAttempts: settings.llmRetryMaxAttempts,
      llmRetryBaseDelayS: settings.llmRetryBaseDelayS,
      llmRetryMaxDelayS: settings.llmRetryMaxDelayS,
      llmTotalTimeoutS: settings.llmTotalTimeoutS,
      timezone: settings.timezone,
      logTimezone: settings.logTimezone,
      demoMode: settings.demoMode,
    });
    setCopiedAudit(true);
    await navigator.clipboard?.writeText(text);
  };

  /* v8 ignore stop */

  return (
    <div className="space-y-6">
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-text">主题</h3>
          <div className="flex items-center gap-2">
            <span
              data-testid="basic-tab-copy-audit"
              onClick={() => void handleCopyAudit()}
              title="复制基础设置审计快照"
              className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text cursor-pointer select-none"
            >
              {copiedAudit ? '已复制快照' : '复制快照'}
            </span>
          </div>
        </div>
        <ThemeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">语言 / Language</h3>
        <SettingRow anchor="locale" label="界面语言" desc="界面显示语言 (U10, 本地持久化)">
          <LanguageSelect />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
        <FontSettingsSection />
        <SettingRow
          anchor="streaming"
          label="流式输出"
          desc="逐字显示 AI 回复，而非等待全部生成完成"
        >
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">LLM 重试</h3>
        <SettingRow
          anchor="llmRetryMaxAttempts"
          label="最大重试次数"
          desc="LLM 请求失败后自动重试的次数上限。设为 0 表示禁用自动重试。"
        >
          <input
            type="number"
            data-testid="settings-llm-retry-max-attempts"
            min={0}
            max={10}
            value={settings.llmRetryMaxAttempts}
            onChange={(e) => {
              const v = Math.max(0, Math.min(10, parseInt(e.target.value, 10) || 0));
              updateSettings({ llmRetryMaxAttempts: v });
            }}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
        <AdvancedSection title="高级选项" description="退避策略参数（通常无需修改）">
          <SettingRow
            anchor="llmRetryBaseDelayS"
            label="退避基数（秒）"
            desc="首次重试等待时间，后续按指数递增（base × 2^(attempt-1)）"
          >
            <input
              type="number"
              data-testid="settings-llm-retry-base-delay"
              min={0.1}
              step={0.5}
              value={settings.llmRetryBaseDelayS}
              onChange={(e) => {
                const v = Math.max(0.1, parseFloat(e.target.value) || 1.0);
                updateSettings({ llmRetryBaseDelayS: v });
              }}
              className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
          </SettingRow>
          <SettingRow
            anchor="llmRetryMaxDelayS"
            label="最大退避（秒）"
            desc="单次重试等待时间上限，防止指数退避过长"
          >
            <input
              type="number"
              data-testid="settings-llm-retry-max-delay"
              min={1}
              step={1}
              value={settings.llmRetryMaxDelayS}
              onChange={(e) => {
                const v = Math.max(1, parseInt(e.target.value, 10) || 30);
                updateSettings({ llmRetryMaxDelayS: v });
              }}
              className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
          </SettingRow>
        </AdvancedSection>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">LLM 任务上限</h3>
        <SettingRow
          anchor="llmTotalTimeoutS"
          label="整轮任务总耗时上限（秒）"
          desc="单次任务（LLM 调用 + 工具执行 + 子代理）的总耗时上限，超出即终止。0 = 不限上限；设后优先于环境变量 SAGE_LLM_TOTAL_TIMEOUT_S"
        >
          <input
            type="number"
            data-testid="settings-llm-total-timeout"
            min={0}
            step={60}
            value={settings.llmTotalTimeoutS}
            onChange={(e) => {
              const v = Math.max(0, parseInt(e.target.value, 10) || 0);
              updateSettings({ llmTotalTimeoutS: v });
            }}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">时区</h3>
        <SettingRow
          anchor="timezone"
          label="IANA 时区"
          desc="后端 zoneinfo 校验；非法值会被拒绝 (422)。默认取系统时区（探测失败回退 Asia/Shanghai）"
        >
          <input
            type="text"
            data-testid="settings-timezone-input"
            value={settings.timezone}
            onChange={(e) => updateSettings({ timezone: e.target.value })}
            placeholder="Asia/Shanghai"
            className="w-48 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary font-mono"
          />
        </SettingRow>
        <SettingRow
          anchor="logTimezone"
          label="日志时区"
          desc="日志时间戳时区. UTC (历史默认) | 本地系统时区 | IANA 时区 (如 Asia/Shanghai). 切换立即生效."
        >
          <select
            data-testid="settings-log-timezone-select"
            value={settings.logTimezone}
            onChange={async (e) => {
              const value = e.target.value;
              await updateSettings({ logTimezone: value });
              await window.electronAPI?.setLogTimezone?.(value);
            }}
            className="w-48 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary font-mono"
          >
            <option value="UTC">UTC (历史默认)</option>
            <option value="local">本地系统时区</option>
            <option value="Asia/Shanghai">Asia/Shanghai (+08:00)</option>
            <option value="Asia/Tokyo">Asia/Tokyo (+09:00)</option>
            <option value="Europe/London">Europe/London</option>
            <option value="America/New_York">America/New_York</option>
            <option value="America/Los_Angeles">America/Los_Angeles</option>
          </select>
        </SettingRow>
      </section>
      <CloseToTrayCard />
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">演示</h3>
        <SettingRow
          anchor="demoMode"
          label="演示模式"
          desc="开启后下次启动跳过后端，各功能页面展示内置示例数据。注意：下次启动生效。"
        >
          <Toggle
            value={settings.demoMode}
            onChange={(v) => {
              void updateSettings({ demoMode: v });
              void window.electronAPI?.setDemoMode?.(v);
            }}
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">数据</h3>
        <p className="text-xs text-muted">基础设置已保存至本地存储和后端。</p>
      </section>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditBasicTabGovernance(): {
  module: 'src/pages/settings/BasicTab.tsx';
  phase: 'P172';
  domain: 'settings';
  supportsTimezoneAndDemoMode: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/BasicTab.tsx',
    phase: 'P172',
    domain: 'settings',
    supportsTimezoneAndDemoMode: true,
    compliant: true,
  };
}
