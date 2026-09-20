/**
 * Settings 页面 - 记忆与知识 Tab
 *
 * 包含记忆管理、附件 RAG、上下文轮数限制、自动快照等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { invoke } from '../../shared/api/desktopInvoke';
import { settingsClient } from '../../shared/api/settingsClient';

import { ContextTurnLimitSelect } from './ContextTurnLimitSelect';
import { SettingRow, Toggle } from './components';

/**
 * 发送前自动快照开关。
 *
 * 走后端 preferences KV（auto_checkpoint），producer 在 run 开始前读取。
 */
function AutoCheckpointCard() {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    void settingsClient.getPreference('auto_checkpoint').then((v) => {
      if (mounted) setEnabled(v !== '0');
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
        desc="每轮对话开始前为绑定的工作区创建检查点，可在变更面板一键回滚（默认开）"
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
 * 每日花费限额 (USD) — preferences KV spend_limit_usd
 */
function SpendLimitInput(): JSX.Element {
  const [limit, setLimit] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
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

export function MemoryKnowledgeTab() {
  const { settings, updateSettings } = useSettings();

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow label="自动记忆提取" desc="对话中自动识别并保存关键信息到记忆库">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
        <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框">
          <Toggle
            value={settings.confirmDelete}
            onChange={(v) => updateSettings({ confirmDelete: v })}
          />
        </SettingRow>
        <ContextTurnLimitSelect />
      </section>
      <AutoCheckpointCard />
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">用量控制</h3>
        <SpendLimitInput />
        <p className="text-xs text-muted mt-2">
          详细的用量统计请在主界面查看用量面板。
        </p>
      </section>
    </div>
  );
}
