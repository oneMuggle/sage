import { useEffect, useMemo, useState } from 'react';

import { listModels } from '../../entities/model-catalog/api';
import type { CandidateModel } from '../../entities/model-catalog/types';
import { useSettings } from '../../features/manage-settings/useSettings';
import {
  AGENT_MAX_ITERATIONS_CEILING,
  AGENT_MIN_ITERATIONS,
  type AgentProfile,
  type AgentUpdate,
} from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { NumberField } from '../../shared/ui/NumberField';

import { ToolAllowlistEditor } from './ToolAllowlistEditor';

interface EditAgentFormProps {
  agent: AgentProfile;
  form: Partial<AgentUpdate>;
  onChange: (form: Partial<AgentUpdate>) => void;
  onSave: () => void;
  onCancel: () => void;
}

export function EditAgentForm({ agent, form, onChange, onSave, onCancel }: EditAgentFormProps) {
  // 取值优先用 form 中的草稿值, 缺则回退到 agent 原值。
  // 注: model_config 在 form 中是部分对象, 取时合并 agent 原值的字段。
  const value = <K extends keyof AgentProfile>(key: K): AgentProfile[K] =>
    form[key as keyof AgentUpdate] !== undefined
      ? (form[key as keyof AgentUpdate] as AgentProfile[K])
      : agent[key];

  // M0 (2026-11-03): 模型字段改为目录下拉 —— 候选来自 model catalog，
  // 拉取失败/无端点时回退为自由文本输入，绝不阻塞编辑。
  const { settings } = useSettings();
  const chatEndpointId = settings.modelSelections.chatModel.endpointId;
  const [modelCatalog, setModelCatalog] = useState<CandidateModel[]>([]);
  useEffect(() => {
    setModelCatalog([]);
    if (!chatEndpointId) return;
    let cancelled = false;
    listModels({ endpointId: chatEndpointId, limit: 100, offset: 0 })
      .then((data) => {
        if (!cancelled) setModelCatalog(data.items);
      })
      .catch(() => {
        if (!cancelled) setModelCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, [chatEndpointId]);
  const modelOptions = useMemo(() => {
    const ids = modelCatalog.map((m) => m.model_key.model_id);
    // 当前值不在 catalog 中也保留，允许用户看到并修改已保存的模型
    const current = value('model_config').model;
    if (current && !ids.includes(current)) ids.unshift(current);
    return ids;
  }, [modelCatalog, value('model_config').model]);

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="agent-name" className="block text-sm font-medium mb-1">
          名称
        </label>
        <input
          id="agent-name"
          type="text"
          value={value('name')}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label htmlFor="agent-description" className="block text-sm font-medium mb-1">
          描述
        </label>
        <input
          id="agent-description"
          type="text"
          value={value('description')}
          onChange={(e) => onChange({ ...form, description: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label htmlFor="agent-system-prompt" className="block text-sm font-medium mb-1">
          系统提示
        </label>
        <textarea
          id="agent-system-prompt"
          value={value('system_prompt')}
          onChange={(e) => onChange({ ...form, system_prompt: e.target.value })}
          rows={4}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <ToolAllowlistEditor
        value={value('tools')}
        onChange={(tools) => onChange({ ...form, tools })}
      />

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label htmlFor="agent-model" className="block text-sm font-medium mb-1">
            模型
          </label>
          {modelOptions.length > 0 ? (
            <select
              id="agent-model"
              value={value('model_config').model}
              onChange={(e) =>
                onChange({
                  ...form,
                  model_config: { ...value('model_config'), model: e.target.value },
                })
              }
              className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
            >
              <option value="">（跟随全局模型）</option>
              {modelOptions.map((modelId) => (
                <option key={modelId} value={modelId}>
                  {modelId}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="agent-model"
              type="text"
              value={value('model_config').model}
              onChange={(e) =>
                onChange({
                  ...form,
                  model_config: { ...value('model_config'), model: e.target.value },
                })
              }
              placeholder="跟随全局"
              className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
            />
          )}
        </div>
        <div>
          <label htmlFor="agent-temperature" className="block text-sm font-medium mb-1">
            Temperature
          </label>
          <input
            id="agent-temperature"
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={value('model_config').temperature}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  temperature: parseFloat(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
        <div>
          <label htmlFor="agent-max-tokens" className="block text-sm font-medium mb-1">
            Max Tokens
          </label>
          <input
            id="agent-max-tokens"
            type="number"
            min="256"
            max="8192"
            step="256"
            value={value('model_config').max_tokens}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  max_tokens: parseInt(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
      </div>

      <div>
        <label htmlFor="agent-max-iterations" className="block text-sm font-medium mb-1">
          最大迭代次数
        </label>
        <NumberField
          id="agent-max-iterations"
          value={value('max_iterations') ?? AGENT_MIN_ITERATIONS}
          onChange={(next) => onChange({ ...form, max_iterations: next })}
          min={AGENT_MIN_ITERATIONS}
          max={AGENT_MAX_ITERATIONS_CEILING}
          step={1}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
        <p className="text-xs text-muted mt-1">
          固定预算模式下这是单轮 ReAct 循环的硬上限；自动预算模式下这是初始预算的下限，
          撞到上限后先做完成判定，任务未完成可续跑
        </p>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          取消
        </Button>
        <Button variant="primary" onClick={onSave}>
          保存
        </Button>
      </div>
    </div>
  );
}

export interface EditAgentFormAuditReport {
  schemaVersion: '1.0';
  module: 'src/widgets/agents/EditAgentForm.tsx';
  componentName: 'EditAgentForm';
  hasNameField: boolean;
  hasSystemPromptField: boolean;
  isDirty: boolean;
  exportedAt: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditEditAgentForm(
  name = 'Research Agent',
  systemPrompt = 'You are a helpful research assistant.',
  isDirty = false,
): EditAgentFormAuditReport {
  return {
    schemaVersion: '1.0',
    module: 'src/widgets/agents/EditAgentForm.tsx',
    componentName: 'EditAgentForm',
    hasNameField: name.trim().length > 0,
    hasSystemPromptField: systemPrompt.trim().length > 0,
    isDirty: Boolean(isDirty),
    exportedAt: '2026-10-22',
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportEditAgentFormAuditJson(
  name = 'Research Agent',
  systemPrompt = 'You are a helpful research assistant.',
  isDirty = false,
): string {
  return JSON.stringify(auditEditAgentForm(name, systemPrompt, isDirty), null, 2);
}
