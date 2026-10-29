/**
 * Settings 页面 - 记忆与知识 Tab
 *
 * 包含记忆管理、附件 RAG、上下文轮数限制、自动快照等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useState } from 'react';
import { toast } from 'sonner';

/** 后端确认回执与输入草稿分离：保存中 / 已确认 / 未确认。 */
import { PreferenceSaveStatus } from '../../features/manage-settings/PreferenceSaveStatus';
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import { useSettings } from '../../features/manage-settings/useSettings';
import { memoryApi } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';
import { productMessages } from '../../shared/lib/productMessages';

import { ContextTurnLimitSelect } from './ContextTurnLimitSelect';
import { SettingRow, Toggle } from './components';

/** 清除时每页拉取量 —— 与记忆浏览器页大小一致，避免一次拉爆。 */
const CLEAR_ALL_PAGE_SIZE = 200;
/** 删除请求之间的间隔，避免瞬间打满 IPC 通道。 */
const CLEAR_ALL_BATCH_GAP_MS = 30;

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
  const { t } = useI18n();
  const CLEAR_ALL_CONFIRM_PHRASE = t('settings.knowledge.confirm_phrase');
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
      toast.error(t('settings.knowledge.count_failed'), {
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
        toast.success(t('settings.knowledge.cleared').replace('{count}', String(done)));
      } else {
        toast.warning(
          t('settings.knowledge.cleared_partial')
            .replace('{done}', String(done))
            .replace('{failed}', String(failed)),
          {
            description: t('settings.knowledge.cleared_partial_desc'),
          },
        );
      }
    } catch (e) {
      setPhase('idle');
      toast.error(t('settings.knowledge.clear_failed'), {
        description: e instanceof Error ? e.message : String(e),
      });
    }
  };

  return (
    <section data-testid="clear-all-memories">
      <h3 className="text-sm font-semibold text-text mb-3">
        {t('settings.knowledge.data_clearing')}
      </h3>
      <p className="text-xs text-muted mb-2">{t('settings.knowledge.data_clearing_desc')}</p>

      {phase === 'idle' && (
        <button
          type="button"
          data-testid="clear-all-memories-button"
          onClick={() => void handleCount()}
          className="text-sm px-3 py-1.5 rounded border border-error text-error hover:bg-error/5 transition-colors"
        >
          {t('settings.knowledge.clear_all')}
        </button>
      )}

      {phase === 'counting' && (
        <span className="text-xs text-muted" data-testid="clear-all-counting">
          {t('settings.common.loading')}
        </span>
      )}

      {phase === 'confirm' && (
        <div className="space-y-2" data-testid="clear-all-confirm">
          <p className="text-xs text-text">
            {t('settings.knowledge.confirm_delete_prefix')}{' '}
            <span className="font-semibold text-error">{total ?? 0}</span>{' '}
            {t('settings.knowledge.confirm_delete_suffix')}
            {t('settings.knowledge.confirm_type_prompt')}{' '}
            <code className="font-mono text-error">{CLEAR_ALL_CONFIRM_PHRASE}</code>
            {t('settings.knowledge.confirm_to_confirm')}
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
              {t('settings.knowledge.permanently_delete')}
            </button>
            <button
              type="button"
              data-testid="clear-all-confirm-no"
              onClick={reset}
              className="text-sm px-3 py-1.5 rounded border border-border text-text-secondary hover:bg-bg-hover transition-colors"
            >
              {t('settings.common.cancel')}
            </button>
          </div>
        </div>
      )}

      {phase === 'clearing' && (
        <span className="text-xs text-muted" data-testid="clear-all-progress">
          {progress.failed > 0
            ? t('settings.knowledge.clearing_progress_with_failed')
                .replace('{done}', String(progress.done))
                .replace('{failed}', String(progress.failed))
            : t('settings.knowledge.clearing_progress').replace('{done}', String(progress.done))}
        </span>
      )}

      {phase === 'done' && (
        <div className="flex items-center gap-2" data-testid="clear-all-done">
          <span className="text-xs text-success">
            {progress.failed > 0
              ? t('settings.knowledge.deleted_with_failed')
                  .replace('{done}', String(progress.done))
                  .replace('{failed}', String(progress.failed))
              : t('settings.knowledge.deleted').replace('{done}', String(progress.done))}
          </span>
          <button
            type="button"
            data-testid="clear-all-dismiss"
            onClick={reset}
            className="text-xs px-2 py-1 rounded border border-border text-text-secondary hover:bg-bg-hover"
          >
            {t('settings.common.gotIt')}
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
export function AutoCheckpointCard() {
  const { t } = useI18n();
  const preference = useConfirmedPreference({
    key: 'auto_checkpoint',
    initial: true,
    parse: (value) => value !== '0',
    serialize: (value: boolean) => (value ? '1' : '0'),
  });
  return (
    <section data-testid="auto-checkpoint-section">
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.knowledge.safety_net')}</h3>
      <SettingRow
        anchor="auto_checkpoint"
        label={t('settings.knowledge.auto_checkpoint_label')}
        desc={t('settings.knowledge.auto_checkpoint_desc')}
      >
        {preference.loaded ? (
          <Toggle
            value={preference.value}
            onChange={(value) => {
              if (preference.status !== 'saving') preference.update(value);
            }}
          />
        ) : (
          <span className="text-ui-sm text-muted">…</span>
        )}
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </section>
  );
}

function SpendLimitInput() {
  const { t } = useI18n();
  const preference = useConfirmedPreference({
    key: 'spend_limit_usd',
    initial: '',
    category: 'general',
    optimistic: true,
    parse: (value) => value ?? '',
    serialize: (value: string) => (value === '' ? '0' : value),
  });
  return (
    <>
      <SettingRow
        anchor="spend_limit"
        label={t('settings.knowledge.spend_limit_label')}
        desc={t('settings.knowledge.spend_limit_desc')}
      >
        <input
          type="number"
          step="0.5"
          min="0"
          disabled={!preference.loaded}
          data-testid="settings-spend-limit-input"
          value={preference.value}
          onChange={(event) => {
            const value = event.target.value;
            if (value === '' || (Number.isFinite(Number(value)) && Number(value) >= 0))
              preference.update(value);
          }}
          placeholder="0"
          className="w-24 text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text"
        />
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </>
  );
}

export function MemoryKnowledgeTab() {
  const { settings, updateSettingsStrict } = useSettings();
  const { locale, t } = useI18n();
  const [saving, setSaving] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const saveMemory = async (partial: Parameters<typeof updateSettingsStrict>[0]) => {
    if (saving) return;
    setSaving(true);
    setUnconfirmed(false);
    try {
      await updateSettingsStrict(partial);
    } catch {
      setUnconfirmed(true);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.knowledge.memory_management')}
        </h3>
        <SettingRow
          anchor="autoMemory"
          label={t('settings.knowledge.auto_memory_label')}
          desc={t('settings.knowledge.auto_memory_desc')}
        >
          <Toggle
            value={settings.autoMemory}
            onChange={(value) => {
              void saveMemory({ autoMemory: value });
            }}
          />
        </SettingRow>
        <SettingRow
          anchor="confirmDelete"
          label={t('settings.knowledge.confirm_delete_label')}
          desc={t('settings.knowledge.confirm_delete_short_desc')}
        >
          <Toggle
            value={settings.confirmDelete}
            onChange={(value) => {
              void saveMemory({ confirmDelete: value });
            }}
          />
        </SettingRow>
        {saving && (
          <p role="status" className="text-ui-sm text-muted">
            {productMessages(locale).saving}
          </p>
        )}
        {unconfirmed && (
          <p role="alert" className="text-ui-sm text-error">
            {productMessages(locale).saveFailed}
          </p>
        )}
        <ContextTurnLimitSelect />
      </section>
      <ClearAllMemoriesSection />
      <AutoCheckpointCard />
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">
          {t('settings.knowledge.usage_control')}
        </h3>
        <SpendLimitInput />
        <p className="text-ui-sm text-muted mt-2">{t('settings.knowledge.usage_details_hint')}</p>
      </section>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditMemoryKnowledgeTabGovernance(
  state: {
    memoryEnabled?: boolean;
    knowledgeSourcesCount?: number;
    autoIndexEnabled?: boolean;
  } = {},
): {
  module: 'src/pages/settings/MemoryKnowledgeTab.tsx';
  phase: 'P143';
  memoryEnabled: boolean;
  knowledgeSourcesCount: number;
  autoIndexEnabled: boolean;
  healthy: boolean;
} {
  const memoryEnabled = state.memoryEnabled !== false;
  const knowledgeSourcesCount =
    typeof state.knowledgeSourcesCount === 'number' && Number.isFinite(state.knowledgeSourcesCount)
      ? Math.max(0, Math.trunc(state.knowledgeSourcesCount))
      : 0;
  const autoIndexEnabled = state.autoIndexEnabled !== false;
  return {
    module: 'src/pages/settings/MemoryKnowledgeTab.tsx',
    phase: 'P143',
    memoryEnabled,
    knowledgeSourcesCount,
    autoIndexEnabled,
    healthy: knowledgeSourcesCount >= 0,
  };
}
