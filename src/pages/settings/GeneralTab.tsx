/**
 * Settings 页面 - 通用设置 Tab
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { getDemoModeOverride, setDemoModeOverride } from '../../shared/api/demoRuntime';
import { invoke } from '../../shared/api/desktopInvoke';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { DiagnosticsCard } from '../../widgets/settings/DiagnosticsCard';
import { HooksCard } from '../../widgets/settings/HooksCard';
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

/** U10 (批次 C): 界面语言切换 — useI18n.setLocale + localStorage 持久化 */
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

/** F5 (批次 C): 每日花费限额 (USD) — preferences KV spend_limit_usd */
function SpendLimitInput(): JSX.Element {
  const [limit, setLimit] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // 卸载守卫: vitest 切换测试环境(jsdom→node)后 promise 才 resolve 时,
    // setState 会在无 window 的上下文执行并产生 unhandled rejection
    // (Frontend job 因此间歇红)。get_preference/set_preference 同理均需守卫。
    let mounted = true;
    invoke<{ value: string | null }>('get_preference', { key: 'spend_limit_usd' })
      .then((resp) => {
        if (mounted) setLimit(resp.value ?? '');
      })
      .catch(() => {
        if (mounted) setLimit('');
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const save = (raw: string): void => {
    setLimit(raw);
    const parsed = Number.parseFloat(raw);
    const value = Number.isFinite(parsed) && parsed >= 0 ? String(parsed) : '0';
    invoke('set_preference', { key: 'spend_limit_usd', value, value_type: 'string' }).catch(
      () => undefined,
    );
  };

  return (
    <SettingRow
      label="每日花费限额 (USD)"
      desc="按估算成本拦截当日请求；0 或留空 = 不限。保存即生效"
    >
      <input
        type="number"
        step="0.5"
        min="0"
        disabled={!loaded}
        data-testid="settings-spend-limit-input"
        value={limit}
        onChange={(e) => save(e.target.value)}
        placeholder="0"
        className="w-24 text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text"
      />
    </SettingRow>
  );
}

/**
 * B-2 (round5 批次 B): 发送前自动快照开关。
 *
 * 走后端 preferences KV（auto_checkpoint），producer 在 run 开始前读取——
 * 与 localStorage 的 app_settings 开关（autoMemory 等）不同，本开关后端
 * 必须能读到，因此用 settingsClient 而非 updateSettings。
 */
function AutoCheckpointCard() {
  const [enabled, setEnabled] = useState<boolean | null>(null); // null = 加载中

  useEffect(() => {
    let mounted = true;
    void settingsClient.getPreference('auto_checkpoint').then((v) => {
      if (mounted) setEnabled(v === '1');
    });
    return () => {
      mounted = false;
    };
  }, []);

  const handleToggle = (v: boolean) => {
    setEnabled(v);
    void settingsClient.setPreference('auto_checkpoint', v ? '1' : '0');
  };

  return (
    <section data-testid="auto-checkpoint-section">
      <h3 className="text-sm font-semibold text-text mb-3">安全网</h3>
      <SettingRow
        label="发送前自动快照"
        desc="每轮对话开始前为绑定的工作区创建检查点，可在变更面板一键回滚（默认关）"
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

/**
 * E-2 (round5 批次 E): 关闭即隐藏到托盘——状态由 Electron 主进程持有
 * （JSON 文件，close 事件拦截），因此走 window.electronAPI IPC 而非
 * 后端 preferences KV。
 */
function CloseToTrayCard(): JSX.Element {
  const [enabled, setEnabled] = useState<boolean | null>(null); // null = 加载中

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
    window.electronAPI
      ?.setCloseToTray?.(v)
      .catch(() => undefined);
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
        <h3 className="text-sm font-semibold text-text mb-3">语言 / Language</h3>
        <SettingRow label="界面语言" desc="界面显示语言 (U10, 本地持久化)">
          <LanguageSelect />
        </SettingRow>
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
      <AutoCheckpointCard />
      <CloseToTrayCard />
      <section data-testid="demo-mode-section">
        <h3 className="text-sm font-semibold text-text mb-3">演示</h3>
        <DemoModeSection />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.permission')}</h3>
        <PermissionModeSelector />
      </section>
      <FallbackModelInput />
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
        <NumberField
          label="Run token 预算（tokens，0=不限）"
          dataTestId="orch-run-token-budget"
          value={settings.orch.runTokenBudget}
          onChange={(v) => updateSettings({ orch: { ...settings.orch, runTokenBudget: v } })}
        />
        <SettingRow
          label="子代理自动批准非危险工具"
          desc="编排子代理遇到需审批的工具时,自动放行非危险调用;破坏性/可疑命令与工作区越界仍弹窗确认"
        >
          <Toggle
            value={settings.orch.subagentApprovalMode === 'auto'}
            onChange={(v) =>
              updateSettings({
                orch: { ...settings.orch, subagentApprovalMode: v ? 'auto' : 'ask' },
              })
            }
          />
        </SettingRow>
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
        <h3 className="text-sm font-semibold text-text mb-3">钩子 (Hooks)</h3>
        <HooksCard />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.usage')}</h3>
        <SpendLimitInput />
        <UsagePanel />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">诊断</h3>
        <DiagnosticsCard />
      </section>
    </div>
  );
}
