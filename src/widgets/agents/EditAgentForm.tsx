import { Button } from '../../components/common/Button';
import type { AgentProfile } from '../../lib/api';

interface EditAgentFormProps {
  agent: AgentProfile;
  form: Partial<AgentProfile>;
  onChange: (form: Partial<AgentProfile>) => void;
  onSave: () => void;
  onCancel: () => void;
}

export function EditAgentForm({ agent, form, onChange, onSave, onCancel }: EditAgentFormProps) {
  const value = <K extends keyof AgentProfile>(key: K): AgentProfile[K] =>
    (form[key] !== undefined ? form[key] : agent[key]) as AgentProfile[K];

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">名称</label>
        <input
          type="text"
          value={value('name')}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">描述</label>
        <input
          type="text"
          value={value('description')}
          onChange={(e) => onChange({ ...form, description: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">系统提示</label>
        <textarea
          value={value('system_prompt')}
          onChange={(e) => onChange({ ...form, system_prompt: e.target.value })}
          rows={4}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">模型</label>
          <input
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
          <label className="block text-sm font-medium mb-1">Temperature</label>
          <input
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
          <label className="block text-sm font-medium mb-1">Max Tokens</label>
          <input
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
