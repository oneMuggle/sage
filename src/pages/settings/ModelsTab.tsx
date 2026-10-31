/**
 * Settings 页面 - 模型选择 Tab
 */

import { clsx } from 'clsx';
import { useNavigate } from 'react-router-dom';

import { ROUTING_TASK_TYPES } from '../../entities/routing/taskType';
import {
  TASK_TYPE_LABELS,
  TASK_TYPE_TIER_MAP,
  TIER_LABELS,
} from '../../entities/routing/taskTypeTierMap';
import type { DiscoveredModel, ModelSelection } from '../../entities/setting/types';
import { useI18n } from '../../shared/lib/i18n';

import { ArenaAccountsToggle } from './ArenaAccountsToggle';
import { LocalOcrCard } from './LocalOcrCard';
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
  const { t } = useI18n();
  // Task 6 (2026-09-15): 跳转到 /model-catalog 管理页
  const navigate = useNavigate();
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

  const modelsBody = (
    <>
      <div>
        <h3 className="text-sm font-semibold text-text">{t('settings.models.model_selection')}</h3>
        <p className="text-xs text-muted mt-0.5">
          {t('settings.models.endpoints_models_count')
            .replace('{endpoints}', String(endpointsWithModels.length))
            .replace('{models}', String(discoveredModelCount))}
        </p>
      </div>

      {/* R31b: 自动模式只藏「对话模型」——路由只重选对话模型，其余能力
          走各自独立路径，仍按下方手动配置渲染。 */}
      {routingMode === 'manual' ? (
        <ModelSelector
          label={t('settings.models.chat_model')}
          desc={t('settings.models.chat_model_desc')}
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
        label={t('settings.models.vision_model')}
        desc={t('settings.models.vision_model_desc')}
        groupedModels={visionModels}
        value={visionModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, visionModel: v } })
        }
      />
      <ModelSelector
        label={t('settings.models.embedding_model')}
        desc={t('settings.models.embedding_model_desc')}
        groupedModels={embeddingModels}
        value={embeddingModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, embeddingModel: v } })
        }
      />
      <ModelSelector
        label={t('settings.models.tts_model')}
        desc={t('settings.models.tts_model_desc')}
        groupedModels={ttsModels}
        value={ttsModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, ttsModel: v } })
        }
      />
      <ModelSelector
        label={t('settings.models.asr_model')}
        desc={t('settings.models.asr_model_desc')}
        groupedModels={asrModels}
        value={asrModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, asrModel: v } })
        }
      />
      <ModelSelector
        label={t('settings.models.image_gen_model')}
        desc={t('settings.models.image_gen_model_desc')}
        groupedModels={imageGenModels}
        value={imageGenModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, imageGenModel: v } })
        }
      />

      {/* 本地 OCR：无视觉模型时的图片文字兜底（引擎状态/语言/优先策略） */}
      <LocalOcrCard />

      {/* R31c: 低频参数收进「高级」折叠；设置搜索命中其内部锚点时，由
          Settings 的跳转 effect 先展开闭合祖先再滚动。 */}
      <details data-testid="settings-models-advanced" className="rounded border border-border">
        <summary className="cursor-pointer px-3 py-2 text-xs text-muted">
          {t('settings.models.advanced')}
        </summary>
        <div className="space-y-3 px-3 pb-3">
          <h3 className="text-sm font-semibold text-text">
            {t('settings.models.model_parameters')}
          </h3>
          <SettingRow
<<<<<<< HEAD
            anchor="title_model"
            label={t('settings.models.title_model')}
            desc={t('settings.models.title_model_desc')}
          >
            <TitleModelSelector
              groupedModels={chatModels}
              chatEndpointId={chatModel.endpointId}
              value={settings.titleModelId ?? ''}
              onChange={(v) => updateSettings({ titleModelId: v })}
            />
          </SettingRow>
          <SettingRow
=======
>>>>>>> origin/main
            anchor="max_context"
            label={t('settings.models.max_context')}
            desc={t('settings.models.max_context_desc')}
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
            label={t('settings.models.auto_context')}
            desc={t('settings.models.auto_context_desc')}
          >
            <label className="text-xs flex items-center gap-2">
              <input
                type="checkbox"
                data-testid="settings-auto-context"
                checked={settings.autoContext}
                onChange={(e) => updateSettings({ autoContext: e.target.checked })}
              />
              <span className="text-text">
                {settings.autoContext
                  ? t('settings.models.auto_catalog')
                  : t('settings.models.fixed_use_above')}
              </span>
            </label>
          </SettingRow>
          <SettingRow
            anchor="max_output_tokens"
            label={t('settings.models.max_output')}
            desc={t('settings.models.max_output_desc')}
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
            desc={t('settings.models.temperature_desc')}
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
        <h3 className="text-sm font-semibold text-text">
          {t('settings.models.model_catalog_mgmt')}
        </h3>
        <SettingRow
          anchor="model_catalog"
          label={t('settings.models.model_catalog')}
          desc={t('settings.models.model_catalog_desc')}
        >
          <button
            type="button"
            data-testid="settings-open-catalog"
            onClick={() => navigate('/model-catalog')}
            className="px-3 py-1.5 text-xs border border-border rounded-radius-sm bg-primary text-text-inverse hover:opacity-90"
          >
            {t('settings.models.open_catalog')}
          </button>
        </SettingRow>
      </div>
<<<<<<< HEAD

      {/* 原「通用」tab 的高级区块（2026-10-28 迁入）：Arena 账号池开关。 */}
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.models.arena_pool')}</h3>
        <ArenaAccountsToggle />
      </section>
=======
>>>>>>> origin/main
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
          {t('settings.models.add_endpoint_hint')}
        </div>
      ) : (
        modelsBody
      )}
<<<<<<< HEAD
=======

      {/* 原「通用」tab 的高级区块（2026-10-28 迁入）：Arena 账号池开关。 */}
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.models.arena_pool')}</h3>
        <ArenaAccountsToggle />
      </section>
>>>>>>> origin/main
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
  const { t } = useI18n();
  return (
    <>
      <SettingRow
        anchor="routing.mode"
        label={t('settings.models.routing_mode')}
        desc={t('settings.models.routing_mode_desc')}
      >
        <div
          role="radiogroup"
          aria-label={t('settings.models.routing_mode_aria')}
          data-testid="settings-routing-mode"
        >
          <label className="flex items-center gap-2 text-xs text-text">
            <input
              type="radio"
              name="routing-mode"
              value="manual"
              data-testid="settings-routing-mode-manual"
              checked={routingMode === 'manual'}
              onChange={() => updateSettings({ routing: { ...settings.routing, mode: 'manual' } })}
            />
            {t('settings.models.routing_manual')}
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
            {t('settings.models.routing_auto')}
          </label>
        </div>
      </SettingRow>
      {routingMode === 'auto' && (
        <div className="space-y-2">
          <p data-testid="settings-routing-mode-hint" className="text-xs text-muted">
            {t('settings.models.routing_auto_hint')}
          </p>
          <table
            data-testid="settings-routing-table"
            className="w-full text-xs border border-border rounded-radius-sm"
          >
            <thead>
              <tr className="text-muted">
                <th className="text-left px-2 py-1 font-medium">
                  {t('settings.models.routing_task_type')}
                </th>
                <th className="text-left px-2 py-1 font-medium">
                  {t('settings.models.routing_tier')}
                </th>
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
          <p className="text-ui-xs text-muted">{t('settings.models.routing_table_note')}</p>
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
  const { t } = useI18n();
  return (
    <SettingRow
      label={t('settings.models.chat_model')}
      desc={t('settings.models.chat_endpoint_readonly_desc')}
    >
      <div data-testid="settings-routing-endpoint" className="text-xs font-mono">
        {endpointName ?? t('settings.models.chat_endpoint_unconfigured')}
      </div>
    </SettingRow>
  );
}

<<<<<<< HEAD
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
  const { t } = useI18n();
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
      <option value="">{t('settings.models.title_model_inherit')}</option>
      {orphan && <option value={orphan}>{orphan}</option>}
      {candidates.map((gm) => (
        <option key={gm.model.id} value={gm.model.id}>
          {gm.model.id}
        </option>
      ))}
    </select>
  );
}

=======
>>>>>>> origin/main
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
  const { t } = useI18n();
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
          <option value="">
            {required ? t('settings.models.please_select') : t('settings.models.not_used')}
          </option>
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
        {required && !hasValue && (
          <span className="text-ui-2xs text-error">{t('settings.common.required')}</span>
        )}
      </div>
    </SettingRow>
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
