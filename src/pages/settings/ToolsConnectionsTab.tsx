/**
 * Settings 页面 - 工具与连接 Tab
 *
 * 包含权限模式、Hooks、网关、降级模型等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { permissionApi } from '../../shared/api/permissionApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { GatewayCard } from '../../widgets/settings/GatewayCard';
import { HooksCard } from '../../widgets/settings/HooksCard';

import { SettingRow, Toggle } from './components';

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
      <TrustEscalationSection />
    </>
  );
}

/**
 * P2-5 渐进式授权。
 *
 * 连续 N 次手动批准某工具后，之后的常规调用自动放行 —— 对标 Claude Code /
 * Codex 的 progressive delegation。默认关闭：未经用户显式同意的自动放行
 * 是 PHILOSOPHY 明令禁止的黑盒决策。
 *
 * 两条如实告知（不夸大承诺）：
 * - 只对**常规操作**生效。破坏性/可疑命令、写工作区外、无法静态评估风险的
 *   工具（skill/repl）永远保留人工审批。
 * - 自动放行的决策会落审计台账（answered_by='trust'），事后可区分「你点的」
 *   与「系统放行的」。
 */
function TrustEscalationSection(): JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [threshold, setThreshold] = useState(3);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consecutive, setConsecutive] = useState<Record<string, number>>({});

  useEffect(() => {
    let mounted = true;
    permissionApi
      .getTrustPolicy()
      .then((state) => {
        if (!mounted) return;
        setEnabled(state.enabled);
        setThreshold(state.threshold);
        setConsecutive(state.consecutive);
      })
      .catch((e: unknown) => {
        if (mounted) setError(e instanceof Error ? e.message : '读取渐进式授权策略失败');
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const persist = (nextEnabled: boolean, nextThreshold: number) => {
    setSaving(true);
    setError(null);
    permissionApi
      .setTrustPolicy(nextEnabled, nextThreshold)
      .then((state) => {
        setEnabled(state.enabled);
        setThreshold(state.threshold);
        return permissionApi.getTrustPolicy();
      })
      .then((state) => setConsecutive(state.consecutive))
      .catch((e: unknown) => {
        // 写失败必须回滚 UI 状态 —— 开关显示「开」但后端没开是最坏的撒谎
        setError(e instanceof Error ? e.message : '保存失败');
        permissionApi
          .getTrustPolicy()
          .then((state) => {
            setEnabled(state.enabled);
            setThreshold(state.threshold);
          })
          .catch(() => {
            /* 读取也失败时保持当前显示，由错误提示说明 */
          });
      })
      .finally(() => setSaving(false));
  };

  const trustEntries = Object.entries(consecutive).filter(([, n]) => n > 0);

  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="trust-escalation-section">
      <SettingRow
        label="渐进式授权（连续批准后自动放行）"
        desc={`你对某个常规操作连续手动批准 ${threshold} 次后，之后同类调用不再逐次弹窗。破坏性命令、写出工作区、无法静态评估的工具仍会逐次询问。`}
      >
        <Toggle
          value={enabled}
          onChange={(v) => {
            setEnabled(v);
            persist(v, threshold);
          }}
          testId="trust-escalation-toggle"
        />
      </SettingRow>
      {enabled ? (
        <SettingRow
          label="触发次数"
          desc="越高越保守。连续批准期间只要拒绝过一次，计数立即归零重来。"
        >
          <input
            type="number"
            min={1}
            max={20}
            data-testid="trust-escalation-threshold"
            value={threshold}
            disabled={saving || !loaded}
            onChange={(e) => {
              const v = Math.max(1, Math.min(20, Number(e.target.value) || 1));
              setThreshold(v);
            }}
            onBlur={() => persist(enabled, threshold)}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-error mt-1">
          {error}
        </p>
      ) : null}
      {enabled && trustEntries.length > 0 ? (
        <div className="mt-2" data-testid="trust-escalation-trust-list">
          <p className="text-xs text-muted">已积累的信任（连续手动批准次数）：</p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {trustEntries.map(([key, n]) => {
              const tool = key.split('|').slice(1).join('|') || key;
              return (
                <li
                  key={key}
                  className="rounded border border-border px-1.5 py-0.5 text-[11px] text-text-secondary"
                >
                  {tool} · {n}
                  {n >= threshold ? ' · 已达阈值' : ''}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
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
