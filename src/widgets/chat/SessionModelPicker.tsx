// src/widgets/chat/SessionModelPicker.tsx
//
// U8 会话级模型切换（对标增强第二轮批次 B,G5 收尾）。
// 会话级覆盖优先于全局设置（后端 llm_factory 三级解析）;
// "跟随全局" 即清除覆盖。只切模型不改端点(端点恒取全局选择)。
//
// Task 7 (2026-10-28): 智能路由自动模式 + 模型 tier 分组。
// - routing.mode === 'auto' 时不再渲染写 override 的 <select>，改为建议性的
//   路由面板（任务类型 + routeModel 预览）。真正的逐条选型在服务端发生（R17）。
// - 手动模式的候选列表在有 catalog 数据时按 快速/均衡/强力/未分类 分组（R27）。

import { Bot } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { getEffective, listModels } from '../../entities/model-catalog/api';
import type { CandidateModel } from '../../entities/model-catalog/types';
import { routeModel } from '../../entities/routing/api';
import {
  ROUTING_TASK_TYPES,
  getRoutingTaskType,
  setRoutingTaskType,
  type RoutingTaskType,
} from '../../entities/routing/taskType';
import type { RouteResponse, Tier } from '../../entities/routing/types';
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

/** tier 分组的固定顺序（R27）：快速 → 均衡 → 强力 → 未分类。 */
const TIER_GROUPS: readonly { tier: Tier | null; label: string }[] = [
  { tier: 'fast', label: '快速' },
  { tier: 'balanced', label: '均衡' },
  { tier: 'powerful', label: '强力' },
  { tier: null, label: '未分类' },
];

/** 任务类型的中文显示名（只在这里，不污染无 UI 依赖的 taskType 模块）。 */
const TASK_TYPE_LABELS: Record<RoutingTaskType, string> = {
  chat: '聊天',
  simple_chat: '简单问答',
  code_generation: '代码生成',
  code_review: '代码审查',
  analysis: '深度分析',
  writing: '写作',
  translation: '翻译',
  summarization: '摘要',
  vision_task: '图像理解',
};

interface PickerOption {
  modelId: string;
  endpointName: string;
  endpointId: string;
  tier: Tier | null; // 来自 catalog；平铺回退路径为 null
  contextTokens: number | null;
  priceLabel: string | null; // `${input}/${output} USD/M`，任一为空则 null
}

/** catalog 的 tier 是宽松字符串；未知值归入「未分类」。 */
function normalizeTier(tier: string | null | undefined): Tier | null {
  return tier === 'fast' || tier === 'balanced' || tier === 'powerful' ? tier : null;
}

function buildPriceLabel(price: CandidateModel['price'] | undefined): string | null {
  const input = price?.input_per_million;
  const output = price?.output_per_million;
  if (!input || !output) return null;
  return `${input}/${output} USD/M`;
}

function formatCatalogOptionLabel(option: PickerOption): string {
  const parts = [option.modelId];
  if (option.contextTokens != null) parts.push(formatTokens(option.contextTokens));
  if (option.priceLabel) parts.push(option.priceLabel);
  return parts.join(' · ');
}

export function formatSessionModelPickerMarkdown(params: {
  sessionId: string | null;
  override: string | null;
  globalModelId: string | null;
  optionCount: number;
}): string {
  return [
    '# 会话模型选择状态 (Session Model Picker Summary)',
    '',
    `- **会话 ID**: ${params.sessionId ? `\`${params.sessionId}\`` : '未选择'}`,
    `- **会话覆盖模型**: ${params.override ? `\`${params.override}\`` : '跟随全局'}`,
    `- **全局默认模型**: ${params.globalModelId ? `\`${params.globalModelId}\`` : '未设置'}`,
    `- **可用候选模型数**: ${params.optionCount}`,
  ].join('\n');
}

export function formatSessionModelPickerJson(params: {
  sessionId: string | null;
  override: string | null;
  globalModelId: string | null;
  optionCount: number;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
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

  // R24: 只有字面量 'auto' 开启自动路由；缺省/缺失一律按手动处理。
  const autoMode = settings.routing?.mode === 'auto';
  const chatEndpointId = settings.modelSelections.chatModel.endpointId;

  // R27: tier 分组数据源 —— model catalog（与 TaskModelAdvisor 同一用法）。
  // 失败/无端点 → []，手动模式回退到 discoveredModels 的平铺列表。
  const [catalog, setCatalog] = useState<CandidateModel[]>([]);
  useEffect(() => {
    setCatalog([]);
    if (!chatEndpointId) return;
    let cancelled = false;
    listModels({ endpointId: chatEndpointId, limit: 100, offset: 0 })
      .then((data) => {
        if (!cancelled) setCatalog(data.items);
      })
      .catch(() => {
        // 离线 / 后端不可用：静默回退平铺列表（R27），不给用户 toast。
        if (!cancelled) setCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, [chatEndpointId]);

  // 候选项：catalog 非空时按当前聊天端点整理并带 tier/窗口/价格；
  // 否则保持原 discoveredModels 的平铺列表（现有测试依赖该回退）。
  const options: PickerOption[] = useMemo(() => {
    if (catalog.length > 0 && chatEndpointId) {
      const endpointName =
        settings.endpoints.find((ep) => ep.id === chatEndpointId)?.name ?? chatEndpointId;
      return catalog.map((m) => ({
        modelId: m.model_key.model_id,
        endpointName,
        endpointId: chatEndpointId,
        tier: normalizeTier(m.tier),
        contextTokens: m.native ?? m.service ?? null,
        priceLabel: buildPriceLabel(m.price),
      }));
    }
    // 防御性检查: 旧数据/绕过 mergeWithDefaults 的代码路径可能让 discoveredModels 为 null
    //   (data layer mergeWithDefaults 已用 DEFAULT_ENDPOINT 兜底, 此处为 belt-and-suspenders).
    return settings.endpoints.flatMap((ep) =>
      (ep.discoveredModels ?? []).map((m) => ({
        modelId: m.id,
        endpointName: ep.name,
        endpointId: ep.id,
        tier: null,
        contextTokens: null,
        priceLabel: null,
      })),
    );
  }, [catalog, chatEndpointId, settings.endpoints]);

  // 自动面板：任务类型选择（持久化）+ routeModel 预览（R28）。
  const [routingOpen, setRoutingOpen] = useState(false);
  const [taskType, setTaskType] = useState<RoutingTaskType>(() => getRoutingTaskType());
  const [routePreview, setRoutePreview] = useState<RouteResponse | null>(null);
  const [routeError, setRouteError] = useState(false);

  useEffect(() => {
    // 面板关闭时不发请求（现有 9 个手动模式用例不会多出网络调用）。
    if (!autoMode || !routingOpen) return;
    // 先清掉上一个会话的预览，再去等覆盖读取完成。
    setRoutePreview(null);
    setRouteError(false);
    // 覆盖读取完成前不下结论，避免先打出 routeModel 再发现会话已锁定。
    if (sessionId && !loaded) return;
    // R23/R28: 已锁定会话 → 只提示，不预览。
    if (override) return;
    if (!chatEndpointId) return;
    let cancelled = false;
    routeModel({
      task_type: taskType,
      context_length: settings.maxContext ?? 4096,
      required_capabilities: ['chat'],
      endpoint_id: chatEndpointId,
    })
      .then((res) => {
        if (!cancelled) setRoutePreview(res);
      })
      .catch(() => {
        // 离线 / 路由服务不可用：只展示「不可用」，不抛错、不 toast。
        if (!cancelled) setRouteError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [
    autoMode,
    routingOpen,
    sessionId,
    loaded,
    override,
    taskType,
    chatEndpointId,
    settings.maxContext,
  ]);

  const globalModelId = settings.modelSelections.chatModel.modelId;

  const doSwitch = (value: string): void => {
    if (!sessionId || saving) return;
    // R26: 自动模式绝不写 override —— 包括手动模式遗留的 P1-3 确认按钮
    // （运行中把 routing.mode 切到 auto 时，旧警告仍可能留在页面上）。
    if (autoMode) return;
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

  const handleTaskTypeChange = (next: RoutingTaskType): void => {
    setTaskType(next);
    setRoutingTaskType(next);
    // 预览由上面 effect 依赖 taskType 自动重算。
  };

  const previewModelName = routePreview?.selected_model.model_key?.model_id ?? null;

  return (
    <div
      className="relative flex items-center gap-1.5"
      title="本会话使用的模型(会话级覆盖,仅影响当前对话)"
    >
      <Bot className="w-3.5 h-3.5 text-text-secondary shrink-0" />
      {autoMode ? (
        // R26: 自动模式绝不渲染会写 override 的 <select>；这里只做建议性展示。
        <details
          className="relative"
          data-testid="session-routing-auto"
          onToggle={(event) => setRoutingOpen(event.currentTarget.open)}
        >
          <summary className="text-xs text-text-secondary cursor-pointer select-none">
            自动路由
          </summary>
          <div
            data-testid="session-routing-panel"
            className={`absolute right-0 ${warningPos} z-40 w-80 space-y-1.5 rounded-radius-md border border-border bg-surface p-2.5 shadow-lg text-ui-xs text-text-secondary`}
          >
            <label className="flex items-center gap-1.5">
              <span className="shrink-0">任务类型</span>
              <select
                aria-label="任务类型"
                data-testid="routing-task-type"
                value={taskType}
                onChange={(event) => handleTaskTypeChange(event.target.value as RoutingTaskType)}
                className="flex-1 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-1.5 py-1 outline-none hover:bg-bg-hover focus:border-primary"
              >
                {ROUTING_TASK_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {TASK_TYPE_LABELS[type]}
                  </option>
                ))}
              </select>
            </label>
            {override ? (
              <p data-testid="routing-locked">本会话已锁定 {override}，自动路由不生效</p>
            ) : !chatEndpointId ? (
              <p>请先在设置中选择聊天模型</p>
            ) : routeError ? (
              <p data-testid="routing-preview-error">路由预览不可用</p>
            ) : routePreview ? (
              <p data-testid="routing-preview">
                模型：{previewModelName ?? '未知模型'} · 档位：{routePreview.selected_model.tier} ·{' '}
                {routePreview.reason}
              </p>
            ) : (
              <p>正在获取路由建议…</p>
            )}
          </div>
        </details>
      ) : (
        <select
          aria-label="会话模型"
          data-testid="session-model-picker"
          value={override ?? ''}
          disabled={!sessionId || !loaded || saving}
          onChange={(e) => handleChange(e.target.value)}
          className="max-w-56 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-1.5 py-1 outline-none hover:bg-bg-hover focus:border-primary disabled:opacity-50 truncate"
        >
          <option value="">跟随全局{globalModelId ? ` (${globalModelId})` : '（未设置）'}</option>
          {catalog.length > 0 && chatEndpointId ? (
            <>
              {TIER_GROUPS.map((group) => {
                const groupOptions = options.filter((opt) => opt.tier === group.tier);
                if (groupOptions.length === 0) return null;
                return (
                  <optgroup key={group.label} label={group.label}>
                    {groupOptions.map((opt) => (
                      <option key={`${opt.endpointId}/${opt.modelId}`} value={opt.modelId}>
                        {formatCatalogOptionLabel(opt)}
                      </option>
                    ))}
                  </optgroup>
                );
              })}
            </>
          ) : (
            options.map((opt) => (
              <option key={`${opt.endpointId}/${opt.modelId}`} value={opt.modelId}>
                {opt.modelId} · {opt.endpointName}
              </option>
            ))
          )}
        </select>
      )}
      {override && (
        <span className="text-ui-xs text-amber-600 dark:text-amber-400 shrink-0">覆盖</span>
      )}
      {!autoMode && pendingSwitch && (
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
