import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select';

export interface ModelOption {
  modelId: string;
  endpointName: string;
}

export interface ModelPickerProps {
  value: string | null;
  onChange: (modelId: string | null) => void;
  models: ModelOption[];
  globalModelId: string | null;
}

export function ModelPicker({ value, onChange, models, globalModelId }: ModelPickerProps) {
  const selectedModel = models.find((m) => m.modelId === value);

  return (
    <Select
      value={value ?? 'global'}
      onValueChange={(val) => onChange(val === 'global' ? null : val)}
    >
      <SelectTrigger aria-label="选择模型" className="w-56">
        <SelectValue placeholder="选择模型">
          {selectedModel
            ? `${selectedModel.modelId} · ${selectedModel.endpointName}`
            : `跟随全局${globalModelId ? ` (${globalModelId})` : '（未设置）'}`}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="global">
          跟随全局{globalModelId ? ` (${globalModelId})` : '（未设置）'}
        </SelectItem>
        {models.length > 0 ? (
          models.map((model) => (
            <SelectItem key={`${model.endpointName}/${model.modelId}`} value={model.modelId}>
              {model.modelId} · {model.endpointName}
            </SelectItem>
          ))
        ) : (
          <div className="px-2 py-1.5 text-sm text-muted">暂无可用模型</div>
        )}
      </SelectContent>
    </Select>
  );
}
