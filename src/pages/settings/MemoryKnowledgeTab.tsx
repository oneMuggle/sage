/**
 * Settings 页面 - 记忆与知识 Tab
 *
 * 包含记忆管理、附件 RAG、上下文轮数限制、自动快照等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useSettings } from '../../features/manage-settings/useSettings';
import { memoryApi } from '../../shared/api';
import { invoke } from '../../shared/api/desktopInvoke';
import { settingsClient } from '../../shared/api/settingsClient';

import { ContextTurnLimitSelect } from './ContextTurnLimitSelect';
import { SettingRow, Toggle } from './components';

/** 清除时每页拉取量 —— 与记忆浏览器页大小一致，避免一次拉爆。 */
const CLEAR_ALL_PAGE_SIZE = 200;
/** 删除请求之间的间隔，避免瞬间打满 IPC 通道。 */
const CLEAR_ALL_BATCH_GAP_MS = 30;
/** 二次确认需原样输入的短语（对标 Claude Reset 的不可逆防护）。 */
const CLEAR_ALL_CONFIRM_PHRASE = '清除全部记忆';

type ClearPhase = 'idle' | 'counting' | 'confirm' | 'clearing' | 'done';

/**
 * P1-1: 「暂停新增」与「彻底清除」必须分离。
 *
 * 此前只有 `autoMemory` 开关（关闭=停止新增），没有任何清除入口 ——
 * 叠加 P0 之前 deleteMemory 零调用，用户事实上无法清空记忆。对标
 * Claude 的 Pause / Reset 二分：Pause 保留存量、Reset 彻底删除，
 * 且 Reset 需要显式确认。关掉开关不会删除已有内容，这一点必须在
 * UI 上说清楚，否则用户会误以为"关了就没了"。
 */
function ClearAllMemoriesSection() {
  const [phase, setPhase] = useState<ClearPhase>('idle');
  const [total, setTotal] = useState<number | null>(null);
  const [typed, setTyped] = useState('');
  const [progress, setProgress] = useState({ done: 0, failed: 0 });

  const reset = () => {
    setPhase('idle');
    setTotal(null);
    setTyped('');
    setProgress({ done: 0, failed: 0 });
  };

  const handleCount = async () => {
    setPhase('counting');
    try {
      const first = await memoryApi.getMemories(undefined, 1, CLEAR_ALL_PAGE_SIZE);
      setTotal(first.total);
      setPhase('confirm');
    } catch (e) {
      setPhase('idle');
      toast.error('统计记忆数量失败', {
        description: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const handleClear = async () => {
    if (phase !== 'confirm' || typed.trim() !== CLEAR_ALL_CONFIRM_PHRASE) return;
    setPhase('clearing');
    let done = 0;
    let failed = 0;
    try {
      // 分页扫描直到拉空 —— 清除过程中列表会收缩，故按 page 递增直到空页。
      let page = 1;
      // 上限防御：正常远小于此，仅防止后端分页异常导致死循环。
      for (let guard = 0; guard < 500; guard += 1) {
        const batch = await memoryApi.getMemories(undefined, page, CLEAR_ALL_PAGE_SIZE);
        if (batch.items.length === 0) break;
        for (const item of batch.items) {
          try {
            await memoryApi.deleteMemory(item.id);
            done += 1;
          } catch {
            // 单条失败不中断整体：如实计数并报告，不谎称"全部清除"
            failed += 1;
          }
        }
        setProgress({ done, failed });
        if (batch.items.length < CLEAR_ALL_PAGE_SIZE) break;
        page += 1;
        await new Promise((r) => setTimeout(r, CLEAR_ALL_BATCH_GAP_MS));
      }
      setProgress({ done, failed });
      setPhase('done');
      if (failed === 0) {
        toast.success(`已清除 ${done} 条记忆`);
      } else {
        toast.warning(`已清除 ${done} 条，${failed} 条失败`, {
          description: '失败项可能仍保留在记忆库中，请重试或逐条删除。',
        });
      }
    } catch (e) {
      setPhase('idle');
      toast.error('清除记忆失败', {
        description: e instanceof Error ? e.message : String(e),
      });
    }
  };

  return (
    <section data-testid="clear-all-memories">
      <h3 className="text-sm font-semibold text-text mb-3">数据清除</h3>
      <p className="text-xs text-muted mb-2">
        永久删除记忆库中的全部条目。此操作不可撤销，也无法通过「自动记忆提取」开关恢复 ——
        关闭那个开关只是停止新增。
      </p>

      {phase === 'idle' && (
        <button
          type="button"
          data-testid="clear-all-memories-button"
          onClick={() => void handleCount()}
          className="text-sm px-3 py-1.5 rounded border border-error text-error hover:bg-error/5 transition-colors"
        >
          清除全部记忆…
        </button>
      )}

      {phase === 'counting' && (
        <span className="text-xs text-muted" data-testid="clear-all-counting">
          正在统计…
        </span>
      )}

      {phase === 'confirm' && (
        <div className="space-y-2" data-testid="clear-all-confirm">
          <p className="text-xs text-text">
            将永久删除 <span className="font-semibold text-error">{total ?? 0}</span> 条记忆。
            请输入 <code className="font-mono text-error">{CLEAR_ALL_CONFIRM_PHRASE}</code> 以确认。
          </p>
          <input
            type="text"
            data-testid="clear-all-confirm-input"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={CLEAR_ALL_CONFIRM_PHRASE}
            className="w-full max-w-xs px-2 py-1 border border-border rounded-radius-sm text-xs bg-surface text-text placeholder:text-muted"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="clear-all-confirm-yes"
              disabled={typed.trim() !== CLEAR_ALL_CONFIRM_PHRASE}
              onClick={() => void handleClear()}
              className="text-sm px-3 py-1.5 rounded border border-error bg-error/10 text-error disabled:opacity-40 transition-colors"
            >
              永久删除
            </button>
            <button
              type="button"
              data-testid="clear-all-confirm-no"
              onClick={reset}
              className="text-sm px-3 py-1.5 rounded border border-border text-text-secondary hover:bg-bg-hover transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {phase === 'clearing' && (
        <span className="text-xs text-muted" data-testid="clear-all-progress">
          正在清除… {progress.done} 条成功
          {progress.failed > 0 ? ` / ${progress.failed} 条失败` : ''}
        </span>
      )}

      {phase === 'done' && (
        <div className="flex items-center gap-2" data-testid="clear-all-done">
          <span className="text-xs text-success">
            已删除 {progress.done} 条{progress.failed > 0 ? `（${progress.failed} 条失败）` : ''}
          </span>
          <button
            type="button"
            data-testid="clear-all-dismiss"
            onClick={reset}
            className="text-xs px-2 py-1 rounded border border-border text-text-secondary hover:bg-bg-hover"
          >
            知道了
          </button>
        </div>
      )}
    </section>
  );
}

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
        <SettingRow
          label="自动记忆提取"
          desc="对话中自动识别并保存关键信息到记忆库。关闭只停止新增，已记住的内容仍保留——彻底清除请用下方「清除全部记忆」。"
        >
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
      <ClearAllMemoriesSection />
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
