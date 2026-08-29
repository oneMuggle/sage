/**
 * Settings 页面 - 通用设置 Tab
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { getDemoModeOverride, setDemoModeOverride } from '../../shared/api/demoRuntime';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { DiagnosticsCard } from '../../widgets/settings/DiagnosticsCard';
import { UsagePanel } from '../../widgets/settings/UsagePanel';

import { ThemeSelector } from './ThemeSelector';
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
    </>
  );
}

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

/**
 * 演示模式开关 (2026-08-27): 用户开启后, renderer 立即通过 IPC 写
 * `<userData>/sage-demo-mode.json`; 下次启动 main 进程读取该文件
 * 决定是否跳过 Python 后端 spawn. 当前会话不会立即生效, 需重启应用.
 * "打开演示页面" 按钮在开启或关闭状态下都可点击 (路由是 frontend-only).
 */
function DemoModeSection() {
  const { settings, updateSettings } = useSettings();
  const [persisting, setPersisting] = useState(false);
  const [persistError, setPersistError] = useState<string | null>(null);

  const handleToggle = async (next: boolean): Promise<void> => {
    setPersistError(null);
    setPersisting(true);
    const wasDemoProcess = getDemoModeOverride() === true;
    try {
      await updateSettings({ demoMode: next });
      const result = await window.electronAPI?.setDemoMode?.(next);
      if (result && result.ok === false) {
        throw new Error('无法保存演示模式设置');
      }
      if (!wasDemoProcess) setDemoModeOverride(next);
    } catch (err) {
      setPersistError(err instanceof Error ? err.message : '无法保存演示模式设置');
      try {
        await updateSettings({ demoMode: !next });
        setDemoModeOverride(wasDemoProcess);
      } catch {
        // Keep the visible error when rollback persistence also fails.
      }
    } finally {
      setPersisting(false);
    }
  };

  return (
    <>
      <SettingRow label="演示模式" desc="开启后下次启动跳过后端，各功能页面展示内置示例数据">
        <Toggle
          value={settings.demoMode}
          disabled={persisting}
          onChange={(v) => {
            void handleToggle(v);
          }}
        />
      </SettingRow>
      {persisting && <div className="text-xs text-muted mt-1">正在保存…</div>}
      {persistError && (
        <div className="text-xs text-error mt-1" data-testid="demo-mode-error">
          保存失败：{persistError}
        </div>
      )}
      <p className="text-[10px] text-muted mt-2 leading-relaxed">
        注意：「跳过后端」在下次启动 Electron 时生效；页面数据切换即时生效。
      </p>
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
        <h3 className="text-sm font-semibold text-text mb-3">时区 (Task 1 2026-08-23)</h3>
        <SettingRow
          label="IANA 时区"
          desc="后端 zoneinfo 校验；非法值会被拒绝 (422)。默认 Asia/Shanghai"
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
      <section data-testid="demo-mode-section">
        <h3 className="text-sm font-semibold text-text mb-3">演示</h3>
        <DemoModeSection />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.permission')}</h3>
        <PermissionModeSelector />
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
        <NumberField
          label="子代理迭代上限"
          dataTestId="orch-max-subagent-iterations"
          value={settings.orch.maxSubagentIterations}
          onChange={(v) => updateSettings({ orch: { ...settings.orch, maxSubagentIterations: v } })}
        />
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
