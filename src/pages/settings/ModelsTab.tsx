/**
 * Settings 页面 - 模型选择 Tab
 */

import { clsx } from 'clsx';

import type { DiscoveredModel, ModelSelection } from '../../entities/setting/types';

import type { EndpointsTabProps } from './components';
import { SettingRow } from './components';

/** A model entry grouped by its source endpoint for the dropdown */
interface GroupedModel {
  endpointId: string;
  endpointName: string;
  model: DiscoveredModel;
}

export function ModelsTab({ settings, updateSettings }: EndpointsTabProps) {
  const endpointsWithModels = settings.endpoints.filter((ep) => ep.discoveredModels.length > 0);

  if (endpointsWithModels.length === 0) {
    return (
      <div className="text-center text-muted py-12 text-sm">
        请先在"端点"标签页中添加端点并测试连接
      </div>
    );
  }

  // Build grouped model lists per capability
  const groupModels = (capability: DiscoveredModel['capabilities'][number]): GroupedModel[] =>
    endpointsWithModels.flatMap((ep) =>
      ep.discoveredModels
        .filter((m) => m.capabilities.includes(capability))
        .map((model) => ({ endpointId: ep.id, endpointName: ep.name, model })),
    );

  const chatModels = groupModels('chat');
  const visionModels = groupModels('vision');
  const embeddingModels = groupModels('embedding');

  const { chatModel, visionModel, embeddingModel } = settings.modelSelections;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">模型选择</h3>
          <p className="text-xs text-muted mt-0.5">
            {endpointsWithModels.length} 个端点，共{' '}
            {endpointsWithModels.reduce((sum, ep) => sum + ep.discoveredModels.length, 0)} 个模型
          </p>
        </div>
      </div>

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
      <ModelSelector
        label="视觉理解模型"
        desc="用于图片识别（选填）"
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

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text">模型参数</h3>
        <SettingRow label="最大上下文长度" desc="单次对话发送给模型的最大 token 数">
          <input
            type="number"
            min={256}
            max={128000}
            value={settings.maxContext}
            onChange={(e) => updateSettings({ maxContext: Number(e.target.value) })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          />
        </SettingRow>
        <SettingRow label="Temperature" desc="控制输出的随机性，0 最确定，1 最随机">
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
    </div>
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
        {required && !hasValue && <span className="text-[11px] text-error">必填</span>}
      </div>
    </SettingRow>
  );
}
