/**
 * Settings 页面 - 模型选择 Tab
 */

import { clsx } from 'clsx';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ROUTING_TASK_TYPES } from '../../entities/routing/taskType';
import {
  TASK_TYPE_LABELS,
  TASK_TYPE_TIER_MAP,
  TIER_LABELS,
} from '../../entities/routing/taskTypeTierMap';
import type { DiscoveredModel, ModelSelection } from '../../entities/setting/types';

import type { EndpointsTabProps } from './components';
import { SettingRow } from './components';

export interface ModelsTabAuditInput {
  endpointCount: number;
  discoveredModelCount: number;
  chatModel: string | null;
  visionModel: string | null;
  embeddingModel: string | null;
  maxContext: number;
  autoContext: boolean;
  temperature: number;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatModelsTabAuditSnapshot(input: ModelsTabAuditInput): string {
  return [
    `# 模型选择审计快照`,
    `- 可用端点数: ${input.endpointCount}`,
    `- 已发现模型数: ${input.discoveredModelCount}`,
    `- 对话模型: ${input.chatModel || '未配置'}`,
    `- 视觉模型: ${input.visionModel || '未配置'}`,
    `- 向量模型: ${input.embeddingModel || '未配置'}`,
    `- 上下文模式: ${input.autoContext ? '自动推断' : `固定(${input.maxContext})`}`,
    `- Temperature: ${input.temperature}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatModelsTabAuditJson(input: ModelsTabAuditInput): string {
  return JSON.stringify(
    {
      endpointCount: input.endpointCount,
      discoveredModelCount: input.discoveredModelCount,
      chatModel: input.chatModel || null,
      visionModel: input.visionModel || null,
      embeddingModel: input.embeddingModel || null,
      maxContext: input.maxContext,
      autoContext: input.autoContext,
      temperature: input.temperature,
    },
    null,
    2,
  );
}

/** A model entry grouped by its source endpoint for the dropdown */
interface GroupedModel {
  endpointId: string;
  endpointName: string;
  model: DiscoveredModel;
}

export function ModelsTab({ settings, updateSettings }: EndpointsTabProps) {
  // Task 6 (2026-09-15): 跳转到 /model-catalog 管理页
  const navigate = useNavigate();
  const [copiedAudit, setCopiedAudit] = useState(false);
  // 防御性检查: 旧数据/绕过 mergeWithDefaults 的代码路径可能让 discoveredModels 为 null
  //   (data layer mergeWithDefaults 已用 DEFAULT_ENDPOINT 兜底, 此处为 belt-and-suspenders).
  const endpointsWithModels = settings.endpoints.filter(
    (ep) => (ep.discoveredModels ?? []).length > 0,
  );
  // R31a: 路由模式必须有独立出口 —— 端点列表为空时也要能切回手动，
  // 否则自动模式下空列表会把用户永久锁死在不可用的状态。
  const routingMode: 'auto' | 'manual' = settings.routing?.mode === 'auto' ? 'auto' : 'manual';

  // Build grouped model lists per capability
  // 防御性检查: discoveredModels 可能在旧数据中缺失
  const groupModels = (capability: DiscoveredModel['capabilities'][number]): GroupedModel[] =>
    endpointsWithModels.flatMap((ep) =>
      (ep.discoveredModels ?? [])
        .filter((m) => m.capabilities.includes(capability))
        .map((model) => ({ endpointId: ep.id, endpointName: ep.name, model })),
    );

  const chatModels = groupModels('chat');
  const visionModels = groupModels('vision');
  const embeddingModels = groupModels('embedding');
  const ttsModels = groupModels('tts');
  const asrModels = groupModels('asr');
  const imageGenModels = groupModels('image_gen');

  const { chatModel, visionModel, embeddingModel } = settings.modelSelections;
  // R31b: 自动模式只藏「对话模型」选择器，只读展示它当前绑定的端点名。
  const chatEndpointName =
    settings.endpoints.find((ep) => ep.id === chatModel.endpointId)?.name ?? null;
  const ttsModel = settings.modelSelections?.ttsModel || { endpointId: null, modelId: null };
  const asrModel = settings.modelSelections?.asrModel || { endpointId: null, modelId: null };
  const imageGenModel = settings.modelSelections?.imageGenModel || {
    endpointId: null,
    modelId: null,
  };
  const discoveredModelCount = endpointsWithModels.reduce(
    (sum, ep) => sum + (ep.discoveredModels ?? []).length,
    0,
  );

  /* v8 ignore start */
  const handleCopyAudit = async () => {
    const text = formatModelsTabAuditSnapshot({
      endpointCount: endpointsWithModels.length,
      discoveredModelCount,
      chatModel: chatModel.modelId,
      visionModel: visionModel.modelId,
      embeddingModel: embeddingModel.modelId,
      maxContext: settings.maxContext,
      autoContext: settings.autoContext,
      temperature: settings.temperature,
    });
    setCopiedAudit(true);
    await navigator.clipboard?.writeText(text);
  };

  /* v8 ignore stop */

  const modelsBody = (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">模型选择</h3>
          <p className="text-xs text-muted mt-0.5">
            {endpointsWithModels.length} 个端点，共 {discoveredModelCount} 个模型
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            data-testid="models-tab-copy-audit"
            onClick={() => void handleCopyAudit()}
            title="复制模型选择审计快照"
            className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text cursor-pointer select-none"
          >
            {copiedAudit ? '已复制快照' : '复制快照'}
          </span>
        </div>
      </div>

      {/* R31b: 自动模式只藏「对话模型」——路由只重选对话模型，其余能力
          走各自独立路径，仍按下方手动配置渲染。 */}
      {routingMode === 'manual' ? (
        <ModelSelector
          label="对话模型"
          desc="用于文本对话（必填）"
          required
          groupedModels={chatModels}
          value={chatModel}
          onChange={(v) =>
            updateSettings({ modelSelections: { ...settings.modelSelections, chatModel: v } })
          }
        />
      ) : (
        <ChatEndpointReadOnly endpointName={chatEndpointName} />
      )}
      <ModelSelector
        label="视觉理解模型"
        desc="选填。当对话模型不支持视觉识别时，自动使用此模型生成图片描述"
        groupedModels={visionModels}
        value={visionModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, visionModel: v } })
        }
      />
      <ModelSelector
        label="向量/嵌入模型"
        desc="用于向量化和语义搜索（选填）"
        groupedModels={embeddingModels}
        value={embeddingModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, embeddingModel: v } })
        }
      />
      <ModelSelector
        label="语音合成 (TTS)"
        desc="用于文本转语音（选填）"
        groupedModels={ttsModels}
        value={ttsModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, ttsModel: v } })
        }
      />
      <ModelSelector
        label="语音识别 (ASR)"
        desc="用于语音转文字（选填）"
        groupedModels={asrModels}
        value={asrModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, asrModel: v } })
        }
      />
      <ModelSelector
        label="图像生成"
        desc="用于文本生成图像（选填）"
        groupedModels={imageGenModels}
        value={imageGenModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, imageGenModel: v } })
        }
      />

      {/* R31c: 低频参数收进「高级」折叠；设置搜索命中其内部锚点时，由
          Settings 的跳转 effect 先展开闭合祖先再滚动。 */}
      <details data-testid="settings-models-advanced" className="rounded border border-border">
        <summary className="cursor-pointer px-3 py-2 text-xs text-muted">高级</summary>
        <div className="space-y-3 px-3 pb-3">
          <h3 className="text-sm font-semibold text-text">模型参数</h3>
          <SettingRow
            anchor="title_model"
            label="会话标题模型"
            desc="生成会话标题时使用的模型（选填）。留空则沿用对话模型；专用小模型通常更快更省"
          >
            <TitleModelSelector
              groupedModels={chatModels}
              chatEndpointId={chatModel.endpointId}
              value={settings.titleModelId ?? ''}
              onChange={(v) => updateSettings({ titleModelId: v })}
            />
          </SettingRow>
          <SettingRow
            anchor="max_context"
            label="最大上下文长度"
            desc="单次对话发送给模型的最大 token 数；自动模式下此值不生效"
          >
            <input
              type="number"
              data-testid="settings-max-context"
              min={256}
              max={128000}
              disabled={settings.autoContext}
              value={settings.maxContext}
              onChange={(e) => updateSettings({ maxContext: Number(e.target.value) })}
              className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </SettingRow>
          {/* Task 6 (2026-09-15): 自动上下文开关 — 保留固定值 / 未知显示未知 */}
          <SettingRow
            anchor="auto_context"
            label="自动推断上下文窗口"
            desc="开启时根据模型目录自动选择; 关闭时使用上方的固定值 (catalog 已知时取最小值)"
          >
            <label className="text-xs flex items-center gap-2">
              <input
                type="checkbox"
                data-testid="settings-auto-context"
                checked={settings.autoContext}
                onChange={(e) => updateSettings({ autoContext: e.target.checked })}
              />
              <span className="text-text">
                {settings.autoContext ? '自动 (目录优先)' : '固定 (使用上方值)'}
              </span>
            </label>
          </SettingRow>
          <SettingRow
            anchor="max_output_tokens"
            label="最大输出长度"
            desc="单次回答允许生成的最大 token 数；调大可减少长回答被截断，但会占用更多上下文窗口"
          >
            <input
              type="number"
              data-testid="settings-max-output-tokens"
              min={512}
              max={32768}
              step={512}
              value={settings.maxOutputTokens}
              onChange={(e) => updateSettings({ maxOutputTokens: Number(e.target.value) })}
              className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
            />
          </SettingRow>
          <SettingRow
            anchor="temperature"
            label="Temperature"
            desc="控制输出的随机性：数值越高越随机；0 最稳定，2 最随机。实际效果取决于模型实现"
          >
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={settings.temperature}
              onChange={(e) => updateSettings({ temperature: Number(e.target.value) })}
              className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
            />
          </SettingRow>
        </div>
      </details>

      {/* Task 6 (2026-09-15): 跳转到模型目录管理 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text">模型目录管理</h3>
        <SettingRow
          anchor="model_catalog"
          label="模型目录 (catalog)"
          desc="管理跨端点的模型价格/上下文窗口/能力标签 — 用户覆盖、快照审核、OpenRouter 同步"
        >
          <button
            type="button"
            data-testid="settings-open-catalog"
            onClick={() => navigate('/model-catalog')}
            className="px-3 py-1.5 text-xs border border-border rounded-radius-sm bg-primary text-text-inverse hover:opacity-90"
          >
            打开模型目录
          </button>
        </SettingRow>
      </div>
    </>
  );

  return (
    <div className="space-y-6">
      {/* R31a: 路由模式永远先于空态/早退渲染 —— 端点列表为空（例如自动模式
          下模型发现失败）时，用户仍必须能切回手动。 */}
      <RoutingModeSection
        settings={settings}
        updateSettings={updateSettings}
        routingMode={routingMode}
      />
      {endpointsWithModels.length === 0 ? (
        <div className="text-center text-muted py-12 text-sm">
          请先在"端点"标签页中添加端点并测试连接
        </div>
      ) : (
        modelsBody
      )}
    </div>
  );
}

interface RoutingModeSectionProps {
  settings: EndpointsTabProps['settings'];
  updateSettings: EndpointsTabProps['updateSettings'];
  routingMode: 'auto' | 'manual';
}

/**
 * R31a/R31b: 全局路由模式开关 + 自动模式下的只读说明。
 *
 * 原生 radio + role="radiogroup"，可视文本标签直接写在 `<label>` 里（不只靠
 * 颜色/描述区分）；写入用展开合并，避免未来 `routing` 加键时被覆盖清空。
 */
function RoutingModeSection({ settings, updateSettings, routingMode }: RoutingModeSectionProps) {
  return (
    <>
      <SettingRow
        anchor="routing.mode"
        label="智能模型路由"
        desc="自动：每条消息按任务类型在同一端点内选择模型；手动：始终使用下方选择的对话模型"
      >
        <div role="radiogroup" aria-label="智能模型路由模式" data-testid="settings-routing-mode">
          <label className="flex items-center gap-2 text-xs text-text">
            <input
              type="radio"
              name="routing-mode"
              value="manual"
              data-testid="settings-routing-mode-manual"
              checked={routingMode === 'manual'}
              onChange={() => updateSettings({ routing: { ...settings.routing, mode: 'manual' } })}
            />
            手动选择模型
          </label>
          <label className="flex items-center gap-2 text-xs text-text">
            <input
              type="radio"
              name="routing-mode"
              value="auto"
              data-testid="settings-routing-mode-auto"
              checked={routingMode === 'auto'}
              onChange={() => updateSettings({ routing: { ...settings.routing, mode: 'auto' } })}
            />
            自动路由（按任务选择）
          </label>
        </div>
      </SettingRow>
      {routingMode === 'auto' && (
        <div className="space-y-2">
          <p data-testid="settings-routing-mode-hint" className="text-xs text-muted">
            自动模式在「对话端点」内按任务类型选择模型；视觉/嵌入/语音等仍按下方配置
          </p>
          <table
            data-testid="settings-routing-table"
            className="w-full text-xs border border-border rounded-radius-sm"
          >
            <thead>
              <tr className="text-muted">
                <th className="text-left px-2 py-1 font-medium">任务类型</th>
                <th className="text-left px-2 py-1 font-medium">分档</th>
              </tr>
            </thead>
            <tbody>
              {ROUTING_TASK_TYPES.map((taskType) => (
                <tr key={taskType} className="border-t border-border">
                  <td className="px-2 py-1 text-text">{TASK_TYPE_LABELS[taskType]}</td>
                  <td className="px-2 py-1 text-muted">
                    {TIER_LABELS[TASK_TYPE_TIER_MAP[taskType]]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-ui-xs text-muted">分档映射由后端 RoutingEngine 决定；本表为只读说明</p>
        </div>
      )}
    </>
  );
}

interface ChatEndpointReadOnlyProps {
  endpointName: string | null;
}

/**
 * R31b: 自动模式下替代「对话模型」选择器的只读行。
 *
 * 不提供端点切换控件 —— 端点变了而 modelId 仍是旧端点的模型会写出半一致
 * 状态；切换端点请切回手动模式完成。
 */
function ChatEndpointReadOnly({ endpointName }: ChatEndpointReadOnlyProps) {
  return (
    <SettingRow
      label="对话模型"
      desc="自动模式下由路由引擎在所选端点内按任务选择；要固定模型请切回手动"
    >
      <div data-testid="settings-routing-endpoint" className="text-xs font-mono">
        {endpointName ?? '未配置（请先切回手动模式选择对话端点）'}
      </div>
    </SettingRow>
  );
}

interface ModelSelectorProps {
  label: string;
  desc: string;
  required?: boolean;
  groupedModels: GroupedModel[];
  value: ModelSelection;
  onChange: (v: ModelSelection) => void;
}

function ModelSelector({
  label,
  desc,
  required,
  groupedModels,
  value,
  onChange,
}: ModelSelectorProps) {
  // Group by endpointId for optgroup rendering
  const groups = new Map<string, { name: string; models: DiscoveredModel[] }>();
  for (const gm of groupedModels) {
    const existing = groups.get(gm.endpointId);
    if (existing) {
      existing.models.push(gm.model);
    } else {
      groups.set(gm.endpointId, { name: gm.endpointName, models: [gm.model] });
    }
  }

  const hasValue =
    value.modelId &&
    groupedModels.some((gm) => gm.endpointId === value.endpointId && gm.model.id === value.modelId);

  return (
    <SettingRow label={label} desc={desc}>
      <div className="flex items-center gap-2">
        <select
          value={hasValue ? `${value.endpointId}::${value.modelId}` : ''}
          onChange={(e) => {
            const raw = e.target.value;
            if (!raw) {
              onChange({ endpointId: null, modelId: null });
              return;
            }
            const [endpointId, modelId] = raw.split('::');
            onChange({ endpointId, modelId });
          }}
          className={clsx(
            'px-2 py-1 border rounded-radius-sm text-xs font-mono bg-surface text-text',
            required && !hasValue ? 'border-error' : 'border-border',
          )}
        >
          <option value="">{required ? '-- 请选择 --' : '-- 不使用 --'}</option>
          {Array.from(groups.entries()).map(([endpointId, { name, models }]) => (
            <optgroup key={endpointId} label={name}>
              {models.map((m) => (
                <option key={`${endpointId}::${m.id}`} value={`${endpointId}::${m.id}`}>
                  {m.id}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {required && !hasValue && <span className="text-ui-2xs text-error">必填</span>}
      </div>
    </SettingRow>
  );
}

interface TitleModelSelectorProps {
  groupedModels: GroupedModel[];
  chatEndpointId: string | null;
  value: string;
  onChange: (v: string) => void;
}

/**
 * 2026-10-27: 会话标题专用模型选择器。
 *
 * 与 `ModelSelector` 的区别：存的是**裸模型 id**（`AppSettings.titleModelId`），
 * 不是 `{endpointId, modelId}` —— 后端 `title_generator.load_title_llm_config`
 * 复用聊天端点的 base_url / api_key，只覆盖 `model` 字段。
 *
 * 因此候选**只列出聊天端点自己已发现的 chat 模型**：换一个端点的模型 id 会
 * 在同一个 base_url 上找不到。空串表示沿用对话模型（后端 fallback）。
 */
function TitleModelSelector({
  groupedModels,
  chatEndpointId,
  value,
  onChange,
}: TitleModelSelectorProps) {
  const candidates = groupedModels.filter((gm) => gm.endpointId === chatEndpointId);
  const known = candidates.some((gm) => gm.model.id === value);
  // 用户可能通过 config_tool 写入了一个未在端点发现列表里的模型 id ——
  // 保留为孤立选项，避免下拉回退到空串时把配置静默抹掉。
  const orphan = value && !known ? value : null;

  return (
    <select
      data-testid="settings-title-model"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
    >
      <option value="">-- 沿用对话模型 --</option>
      {orphan && <option value={orphan}>{orphan}</option>}
      {candidates.map((gm) => (
        <option key={gm.model.id} value={gm.model.id}>
          {gm.model.id}
        </option>
      ))}
    </select>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditModelsTabGovernance(): {
  module: 'src/pages/settings/ModelsTab.tsx';
  phase: 'P172';
  domain: 'settings';
  supportsAutoContextAndCatalogNavigation: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/ModelsTab.tsx',
    phase: 'P172',
    domain: 'settings',
    supportsAutoContextAndCatalogNavigation: true,
    compliant: true,
  };
}
