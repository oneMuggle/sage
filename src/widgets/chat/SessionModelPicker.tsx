// src/widgets/chat/SessionModelPicker.tsx
//
// U8 会话级模型切换（对标增强第二轮批次 B,G5 收尾）。
// 会话级覆盖优先于全局设置（后端 llm_factory 三级解析）;
// "跟随全局" 即清除覆盖。只切模型不改端点(端点恒取全局选择)。

import { Bot } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getEffective } from '../../entities/model-catalog/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { sessionApi } from '../../shared/api/sessionApi';
import { fetchSessionUsage } from '../../shared/api/usageApi';

interface SessionModelPickerProps {
  sessionId: string | null;
  placement?: 'top' | 'bottom';
}

/** 当前占用超过目标窗口该比例时，切换前先提示（历史会被截断）。 */
const SWITCH_RISK_RATIO = 0.8;

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/** 尚未确认的切换：已预检出「历史会被截断」风险，等用户显式点头。 */
interface PendingSwitch {
  modelId: string;
  windowTokens: number;
  usedTokens: number;
}

export function SessionModelPicker({ sessionId, placement = 'top' }: SessionModelPickerProps) {
  const warningPos = placement === 'bottom' ? 'top-full mt-1.5' : 'bottom-full mb-1.5';
  const { settings } = useSettings();
  const [override, setOverride] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState<PendingSwitch | null>(null);

  // 会话切换时拉取当前覆盖
  useEffect(() => {
    setLoaded(false);
    setOverride(null);
    if (!sessionId) return;
    let cancelled = false;
    sessionApi
      .getModelOverride(sessionId)
      .then((model) => {
        if (!cancelled) setOverride(model);
      })
      .catch(() => {
        /* 拉取失败按"未设置"处理 */
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 候选项:全部端点的已发现模型(与设置页 ModelsTab 同一数据源)
  // 防御性检查: 旧数据/绕过 mergeWithDefaults 的代码路径可能让 discoveredModels 为 null
  //   (data layer mergeWithDefaults 已用 DEFAULT_ENDPOINT 兜底, 此处为 belt-and-suspenders).
  const options = settings.endpoints.flatMap((ep) =>
    (ep.discoveredModels ?? []).map((m) => ({
      modelId: m.id,
      endpointName: ep.name,
      endpointId: ep.id,
    })),
  );

  const globalModelId = settings.modelSelections.chatModel.modelId;

  const doSwitch = (value: string): void => {
    if (!sessionId || saving) return;
    setSaving(true);
    sessionApi
      .setModelOverride(sessionId, value)
      .then((applied) => {
        setOverride(applied);
        toast.success(value ? `本会话模型已切换为 ${value}` : '已恢复跟随全局模型');
      })
      .catch((e: unknown) => {
        toast.error(e instanceof Error ? e.message : '模型切换失败');
      })
      .finally(() => setSaving(false));
  };

  /**
   * P1-3: 消除「盲切换」。
   *
   * 此前切换只弹一句「已切换为 X」，不告知窗口变化 —— 用户换到小窗口模型后
   * 可能突然发现历史被截断。对标 Cursor 的 model switch 提示。
   *
   * 预检拿两路数据：目标模型的 effective 窗口（model catalog 解析）与本会话
   * 当前占用。任一不可得就**不拦截**（未知 ≠ 有风险），照常切换 ——
   * 宁可少拦，不可误拦把正常切换也变成阻碍。
   */
  const handleChange = (value: string): void => {
    if (!sessionId || saving) return;
    const target = options.find((o) => o.modelId === value);
    if (!target) {
      doSwitch(value);
      return;
    }
    void (async () => {
      const [effective, usage] = await Promise.allSettled([
        getEffective(target.endpointId, value),
        fetchSessionUsage(sessionId),
      ]);
      const limits = effective.status === 'fulfilled' ? effective.value?.limits : null;
      const windowTokens = limits?.native ?? limits?.service ?? null;
      const usedTokens =
        usage.status === 'fulfilled' ? (usage.value.last_prompt_tokens ?? null) : null;
      if (
        windowTokens != null &&
        windowTokens > 0 &&
        usedTokens != null &&
        usedTokens > windowTokens * SWITCH_RISK_RATIO
      ) {
        setPendingSwitch({ modelId: value, windowTokens, usedTokens });
        return;
      }
      doSwitch(value);
    })();
  };

  return (
    <div className="relative flex items-center gap-1.5" title="本会话使用的模型(会话级覆盖,仅影响当前对话)">
      <Bot className="w-3.5 h-3.5 text-text-secondary shrink-0" />
      <select
        aria-label="会话模型"
        data-testid="session-model-picker"
        value={override ?? ''}
        disabled={!sessionId || !loaded || saving}
        onChange={(e) => handleChange(e.target.value)}
        className="max-w-56 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-1.5 py-1 outline-none hover:bg-bg-hover focus:border-primary disabled:opacity-50 truncate"
      >
        <option value="">跟随全局{globalModelId ? ` (${globalModelId})` : '（未设置）'}</option>
        {options.map((opt) => (
          <option key={`${opt.endpointName}/${opt.modelId}`} value={opt.modelId}>
            {opt.modelId} · {opt.endpointName}
          </option>
        ))}
      </select>
      {override && (
        <span className="text-[10px] text-amber-600 dark:text-amber-400 shrink-0">覆盖</span>
      )}
      {pendingSwitch && (
        <span
          className={`absolute right-0 ${warningPos} z-40 w-80 rounded-radius-md border border-warning/40 bg-surface p-2.5 shadow-lg flex flex-wrap items-center gap-1.5 text-ui-xs text-warning`}
          data-testid="model-switch-warning"
          role="alert"
        >
          <span>
            {pendingSwitch.modelId} 窗口 {formatTokens(pendingSwitch.windowTokens)}，本对话已用{' '}
            {formatTokens(pendingSwitch.usedTokens)}，超出部分会被截断
          </span>
          <button
            type="button"
            data-testid="model-switch-confirm"
            onClick={() => {
              const next = pendingSwitch.modelId;
              setPendingSwitch(null);
              doSwitch(next);
            }}
            className="px-1.5 py-0.5 rounded border border-yellow-600 hover:bg-yellow-600/10"
          >
            仍然切换
          </button>
          <button
            type="button"
            data-testid="model-switch-cancel"
            onClick={() => setPendingSwitch(null)}
            className="px-1.5 py-0.5 rounded border border-border hover:bg-bg-hover"
          >
            取消
          </button>
        </span>
      )}
    </div>
  );
}
