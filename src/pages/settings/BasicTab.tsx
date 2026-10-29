/**
 * Settings 页面 - 基础设置 Tab
 *
 * 包含外观（主题、语言、字体）和基础对话行为（流式输出、时区、托盘）。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { getInputHistorySize, setInputHistorySize } from '../../shared/lib/hooks/useInputHistory';
import { useI18n } from '../../shared/lib/i18n';

import { AttachmentRagCard } from './AttachmentRagCard';
import { ContextTurnLimitSelect } from './ContextTurnLimitSelect';
import { DemoModeSection } from './DemoModeSection';
import { FontSettingsSection } from './FontSettingsSection';
import { ResetDefaultsSection } from './ResetDefaultsSection';
import { ThemeSelector } from './ThemeSelector';
import { AdvancedSection, SettingRow, Toggle } from './components';

export interface BasicTabAuditInput {
  streaming: boolean;
  llmRetryMaxAttempts: number;
  llmRetryBaseDelayS: number;
  llmRetryMaxDelayS: number;
  llmRetryTotalBudgetS: number;
  llmTotalTimeoutS: number;
  llmProxyTimeoutS: number;
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
    `- 重试总时长预算(秒): ${input.llmRetryTotalBudgetS === 0 ? '不限' : input.llmRetryTotalBudgetS}`,
    `- LLM 任务上限(秒): ${input.llmTotalTimeoutS === 0 ? '不限' : input.llmTotalTimeoutS}`,
    `- LLM 代理超时(秒): ${input.llmProxyTimeoutS}`,
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
      llmRetryTotalBudgetS: input.llmRetryTotalBudgetS,
      llmTotalTimeoutS: input.llmTotalTimeoutS,
      llmProxyTimeoutS: input.llmProxyTimeoutS,
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
  const { locale, setLocale, t } = useI18n();
  return (
    <select
      data-testid="settings-language-select"
      value={locale}
      onChange={(e) => setLocale(e.target.value as 'zh' | 'en')}
      className="text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text"
      aria-label={t('settings.basic.language_aria_label')}
    >
      <option value="zh">{t('settings.basic.lang_chinese')}</option>
      <option value="en">English</option>
    </select>
  );
}

/**
 * 关闭即隐藏到托盘——状态由 Electron 主进程持有
 * （JSON 文件，close 事件拦截），因此走 window.electronAPI IPC。
 */
function CloseToTrayCard(): JSX.Element {
  const { t } = useI18n();
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
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.tray')}</h3>
      <SettingRow
        anchor="close_to_tray"
        label={t('settings.basic.close_to_tray_label')}
        desc={t('settings.basic.close_to_tray_desc')}
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
  const { t } = useI18n();
  const { settings, updateSettings } = useSettings();
  const [inputHistorySize, setInputHistorySizeState] = useState(getInputHistorySize());
  const [proxyTimeoutDraft, setProxyTimeoutDraft] = useState(String(settings.llmProxyTimeoutS));

  useEffect(() => {
    setProxyTimeoutDraft(String(settings.llmProxyTimeoutS));
  }, [settings.llmProxyTimeoutS]);

  // 失焦提交：逐键 clamp 会把 300 改成 500，且无法清空重输。
  const commitProxyTimeout = (): void => {
    const raw = parseInt(proxyTimeoutDraft, 10);
    const v = Number.isFinite(raw) ? Math.max(5, Math.min(1800, raw)) : settings.llmProxyTimeoutS;
    setProxyTimeoutDraft(String(v));
    if (v !== settings.llmProxyTimeoutS) updateSettings({ llmProxyTimeoutS: v });
  };

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.theme')}</h3>
        <ThemeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.basic.language_heading')}
        </h3>
        <SettingRow
          anchor="locale"
          label={t('settings.basic.language_label')}
          desc={t('settings.basic.language_desc')}
        >
          <LanguageSelect />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.appearance')}</h3>
        <FontSettingsSection />
        <SettingRow
          anchor="streaming"
          label={t('settings.basic.streaming_label')}
          desc={t('settings.basic.streaming_desc')}
        >
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.conversation')}</h3>
        <ContextTurnLimitSelect />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.basic.input_history')}
        </h3>
        <SettingRow
          anchor="inputHistorySize"
          label={t('settings.basic.history_size_label')}
          desc={t('settings.basic.history_size_desc')}
        >
          <input
            type="number"
            data-testid="settings-input-history-size"
            min={1}
            max={200}
            value={inputHistorySize}
            onChange={(e) => {
              const raw = parseInt(e.target.value, 10);
              const v = Number.isFinite(raw) ? Math.max(1, Math.min(200, raw)) : 50;
              setInputHistorySize(v);
              setInputHistorySizeState(v);
            }}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.llm_retry')}</h3>
        <SettingRow
          anchor="llmRetryMaxAttempts"
          label={t('settings.basic.retry_max_label')}
          desc={t('settings.basic.retry_max_desc')}
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
        <SettingRow
          anchor="llmRetryTotalBudgetS"
          label={t('settings.basic.retry_total_budget_label')}
          desc={t('settings.basic.retry_total_budget_desc')}
        >
          <input
            type="number"
            data-testid="settings-llm-retry-total-budget"
            min={0}
            max={1800}
            step={10}
            value={settings.llmRetryTotalBudgetS}
            onChange={(e) => {
              const v = Math.max(0, Math.min(1800, parseInt(e.target.value, 10) || 0));
              updateSettings({ llmRetryTotalBudgetS: v });
            }}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
        <AdvancedSection
          title={t('settings.basic.advanced_title')}
          description={t('settings.basic.advanced_desc')}
        >
          <SettingRow
            anchor="llmRetryBaseDelayS"
            label={t('settings.basic.retry_base_label')}
            desc={t('settings.basic.retry_base_desc')}
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
            label={t('settings.basic.llm_retry.max_delay.label')}
            desc={t('settings.basic.llm_retry.max_delay.desc')}
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
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.basic.section.llm_total_limit')}
        </h3>
        <SettingRow
          anchor="llmTotalTimeoutS"
          label={t('settings.basic.llm_total_limit.label')}
          desc={t('settings.basic.llm_total_limit.desc')}
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
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.basic.section.llm_proxy_timeout')}
        </h3>
        <SettingRow
          anchor="llmProxyTimeoutS"
          label={t('settings.basic.llm_proxy_timeout.label')}
          desc={t('settings.basic.llm_proxy_timeout.desc')}
        >
          <input
            type="number"
            data-testid="settings-llm-proxy-timeout"
            min={5}
            max={1800}
            step={5}
            value={proxyTimeoutDraft}
            onChange={(e) => setProxyTimeoutDraft(e.target.value)}
            onBlur={commitProxyTimeout}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.basic.section.timezone')}
        </h3>
        <SettingRow
          anchor="timezone"
          label={t('settings.basic.timezone.label')}
          desc={t('settings.basic.timezone.desc')}
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
          label={t('settings.basic.log_timezone.label')}
          desc={t('settings.basic.log_timezone.desc')}
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
            <option value="UTC">{t('settings.basic.log_timezone.utc')}</option>
            <option value="local">{t('settings.basic.log_timezone.local')}</option>
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
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.section.demo')}</h3>
        <DemoModeSection />
      </section>
      <AttachmentRagCard />
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.basic.section.data')}</h3>
        <ResetDefaultsSection />
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
