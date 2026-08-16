/**
 * Settings 页面 - 通用设置 Tab
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { DiagnosticsCard } from '../../widgets/settings/DiagnosticsCard';
import { UsagePanel } from '../../widgets/settings/UsagePanel';

import { ThemeSelector } from './ThemeSelector';
import { SettingRow, Toggle } from './components';

/**
 * Wave 3 P2-9 编排设置数字输入。部分更新契约：onChange 收到的 v 已通过
 * 非负有限数校验；调用方负责 spread settings.orch 保留其余键。
 */
function NumberField({
  label,
  dataTestId,
  value,
  onChange,
}: {
  label: string;
  dataTestId: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <SettingRow label={label}>
      <input
        type="number"
        data-testid={dataTestId}
        value={value}
        onChange={(e) => {
          // 空输入 = 不修改：Number('') === 0 会经 n >= 0 守卫提交 0，
          // 落库后 load_orch_settings() 读到 0 → asyncio.Semaphore(0) → 编排挂死。
          if (e.target.value === '') return;
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n >= 0) onChange(Math.floor(n));
        }}
        className="w-32 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </SettingRow>
  );
}

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

export function GeneralTab({ resetSettings }: { resetSettings: () => void }) {
  const { settings, updateSettings } = useSettings();
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">主题</h3>
        <ThemeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
        <SettingRow label="流式输出" desc="逐字显示 AI 回复，而非等待全部生成完成">
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">对话</h3>
        <SettingRow label="自动记忆提取" desc="对话中自动识别并保存关键信息到记忆库">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
        <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框">
          <Toggle
            value={settings.confirmDelete}
            onChange={(v) => updateSettings({ confirmDelete: v })}
          />
        </SettingRow>
      </section>
      <section data-testid="orch-settings-section">
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.orch')}</h3>
        <NumberField
          label="最大并发子任务数"
          dataTestId="orch-max-concurrent"
          value={settings.orch.maxConcurrentSubagents}
          onChange={(v) =>
            updateSettings({ orch: { ...settings.orch, maxConcurrentSubagents: v } })
          }
        />
        <NumberField
          label="聚合结果上限（字符）"
          dataTestId="orch-max-aggregate"
          value={settings.orch.maxAggregateChars}
          onChange={(v) => updateSettings({ orch: { ...settings.orch, maxAggregateChars: v } })}
        />
        <NumberField
          label="单结果截断上限（字符）"
          dataTestId="orch-max-subagent-result"
          value={settings.orch.maxSubagentResultChars}
          onChange={(v) =>
            updateSettings({ orch: { ...settings.orch, maxSubagentResultChars: v } })
          }
        />
        <NumberField
          label="子任务重试次数"
          dataTestId="orch-max-retries"
          value={settings.orch.maxRetries}
          onChange={(v) => updateSettings({ orch: { ...settings.orch, maxRetries: v } })}
        />
        <NumberField
          label="Lane 迭代上限"
          dataTestId="orch-max-lane-iterations"
          value={settings.orch.maxLaneIterations}
          onChange={(v) => updateSettings({ orch: { ...settings.orch, maxLaneIterations: v } })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.permission')}</h3>
        <PermissionModeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">数据</h3>
        <button
          onClick={resetSettings}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
        >
          恢复默认设置
        </button>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.usage')}</h3>
        <UsagePanel />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">诊断</h3>
        <DiagnosticsCard />
      </section>
    </div>
  );
}
