/**
 * Settings 页面 - 工具与连接 Tab
 *
 * 包含权限模式、Hooks、网关、降级模型等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { GatewayCard } from '../../widgets/settings/GatewayCard';
import { HooksCard } from '../../widgets/settings/HooksCard';

import { SettingRow } from './components';

/** 与后端 PermissionMode 枚举值一致（backend/tools/permissions.py） */
export const PERMISSION_MODES = ['read_only', 'workspace_write', 'prompt', 'full_access'] as const;
export type PermissionMode = (typeof PERMISSION_MODES)[number];

/**
 * 工具权限模式选择器（M1 工具安全加固）。
 *
 * 持久化走 preferences KV（get_preference / set_preference key='permission_mode'）
 * 而不是 app_settings blob — 后端 load_enforcer_from_settings() 用
 * SettingsRepository.get("permission_mode") 读取（KV 表），且
 * settings_canonicalizer 的 LEGAL_TOP_KEYS 白名单不含 permissionMode，
 * 走 PUT /api/v1/settings 会被 400 拒掉。
 */
function PermissionModeSelector() {
  const { t } = useI18n();
  // 后端未设置时默认 workspace_write（与 DEFAULT_PERMISSION_MODE 一致）
  const [mode, setMode] = useState<PermissionMode>('workspace_write');

  useEffect(() => {
    let cancelled = false;
    settingsClient.getPreference('permission_mode').then((value) => {
      if (cancelled) return;
      if (value && (PERMISSION_MODES as readonly string[]).includes(value)) {
        setMode(value as PermissionMode);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (next: PermissionMode): void => {
    setMode(next);
    // setSettings 式双写在这里不适用（KV 存储无本地 cache 层）；
    // 写入失败由 settingsClient 静默降级 + console.warn。
    void settingsClient.setPreference('permission_mode', next, 'permissions');
  };

  return (
    <>
      <SettingRow
        label={t('settings.permission.mode')}
        desc={t(`settings.permission.mode.${mode}.desc` as TranslationKey)}
      >
        <select
          data-testid="permission-mode-select"
          aria-label={t('settings.permission.mode')}
          value={mode}
          onChange={(e) => handleChange(e.target.value as PermissionMode)}
          className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        >
          {PERMISSION_MODES.map((m) => (
            <option key={m} value={m}>
              {t(`settings.permission.mode.${m}` as TranslationKey)}
            </option>
          ))}
        </select>
      </SettingRow>
      <p className="text-xs text-muted mt-2">{t('settings.permission.rules_hint')}</p>
    </>
  );
}

/**
 * D-1 (round5 批次 D): 主模型重试耗尽后的降级模型——preferences KV
 * fallback_model。留空 = 不降级。producer 在构建 llm_config 时读取。
 */
function FallbackModelInput(): JSX.Element {
  const [model, setModel] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let mounted = true;
    settingsClient
      .getPreference('fallback_model')
      .then((value) => {
        if (mounted) setModel(value ?? '');
      })
      .catch(() => {
        if (mounted) setModel('');
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <SettingRow
      label="降级模型 (fallback)"
      desc="主模型重试耗尽（限流/服务端错误/超时）后自动切换到此模型；留空 = 不降级"
    >
      <input
        type="text"
        data-testid="settings-fallback-model-input"
        disabled={!loaded}
        value={model}
        onChange={(e) => {
          setModel(e.target.value);
          void settingsClient.setPreference('fallback_model', e.target.value.trim());
        }}
        placeholder="例如 gpt-4o-mini"
        className="w-44 text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text font-mono"
      />
    </SettingRow>
  );
}

export function ToolsConnectionsTab() {
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.permission')}</h3>
        <PermissionModeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">模型降级</h3>
        <FallbackModelInput />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">钩子 (Hooks)</h3>
        <HooksCard />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">诊断</h3>
        <GatewayCard platform="telegram" />
        <GatewayCard platform="discord" />
        <GatewayCard platform="slack" />
      </section>
    </div>
  );
}
