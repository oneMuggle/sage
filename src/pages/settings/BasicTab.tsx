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
import { SettingRow, Toggle } from './components';

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

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">主题</h3>
        <ThemeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">语言 / Language</h3>
        <SettingRow label="界面语言" desc="界面显示语言 (U10, 本地持久化)">
          <LanguageSelect />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
        <FontSettingsSection />
        <SettingRow label="流式输出" desc="逐字显示 AI 回复，而非等待全部生成完成">
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">时区</h3>
        <SettingRow
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
