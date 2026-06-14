import { Button } from '../../components/common/Button';
import type { AgentProfile, AgentUpdate } from '../../shared/api/api';

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

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label htmlFor="agent-model" className="block text-sm font-medium mb-1">
            模型
          </label>
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
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
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
