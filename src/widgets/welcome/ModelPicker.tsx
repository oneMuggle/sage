import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select/Select';

/** Task 8: 自动路由哨兵值；仅当全局 routing.mode === 'auto' 时作为选项出现。 */
export const AUTO_MODEL_ID = 'auto';

const AUTO_MODEL_LABEL = '自动路由（按任务选择模型）';

type ModelTier = 'fast' | 'balanced' | 'powerful';

/** tier 分组的固定顺序（R27）：快速 → 均衡 → 强力 → 未分类。 */
const TIER_GROUPS: readonly { tier: ModelTier | null; label: string }[] = [
  { tier: 'fast', label: '快速' },
  { tier: 'balanced', label: '均衡' },
  { tier: 'powerful', label: '强力' },
  { tier: null, label: '未分类' },
];

/** catalog 的 tier 是宽松字符串；未知值归入「未分类」。 */
function normalizeTier(tier: string | null | undefined): ModelTier | null {
  return tier === 'fast' || tier === 'balanced' || tier === 'powerful' ? tier : null;
}

/** `<1000` 原样，`>=1000` 用 `k` 并去掉无意义的小数（128000 → 128k）。 */
function formatContextTokens(tokens: number): string {
  if (tokens < 1000) return String(tokens);
  return `${Number((tokens / 1000).toFixed(1))}k`;
}

function formatGroupedModelLabel(model: ModelOption): string {
  const parts = [`${model.modelId} · ${model.endpointName}`];
  if (model.contextTokens != null) parts.push(formatContextTokens(model.contextTokens));
  if (model.priceLabel) parts.push(model.priceLabel);
  return parts.join(' · ');
}

export interface ModelOption {
  modelId: string;
  endpointName: string;
  tier?: string | null;
  contextTokens?: number | null;
  priceLabel?: string | null;
}

export interface ModelPickerProps {
  value: string | null;
  onChange: (modelId: string | null) => void;
  models: ModelOption[];
  globalModelId: string | null;
  autoAvailable?: boolean;
}

export function ModelPicker({
  value,
  onChange,
  models,
  globalModelId,
  autoAvailable = false,
}: ModelPickerProps) {
  const selectedModel = models.find((m) => m.modelId === value);
  // R27: 至少一个候选项带 tier 才分组；否则保持平铺（现有用例走这条路径）。
  const hasTierData = models.some((model) => model.tier != null);

  const renderModelItem = (model: ModelOption, grouped: boolean) => (
    <SelectItem key={`${model.endpointName}/${model.modelId}`} value={model.modelId}>
      {grouped ? formatGroupedModelLabel(model) : `${model.modelId} · ${model.endpointName}`}
    </SelectItem>
  );

  return (
    <Select
      value={value ?? 'global'}
      onValueChange={(val: string) => {
        if (val === AUTO_MODEL_ID) {
          onChange(AUTO_MODEL_ID);
          return;
        }
        onChange(val === 'global' ? null : val);
      }}
    >
      <SelectTrigger aria-label="选择模型" className="w-56">
        <SelectValue placeholder="选择模型">
          {value === AUTO_MODEL_ID
            ? AUTO_MODEL_LABEL
            : selectedModel
              ? `${selectedModel.modelId} · ${selectedModel.endpointName}`
              : `跟随全局${globalModelId ? ` (${globalModelId})` : '（未设置）'}`}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {autoAvailable && <SelectItem value={AUTO_MODEL_ID}>{AUTO_MODEL_LABEL}</SelectItem>}
        <SelectItem value="global">
          跟随全局{globalModelId ? ` (${globalModelId})` : '（未设置）'}
        </SelectItem>
        {models.length > 0 ? (
          hasTierData ? (
            TIER_GROUPS.map((group) => {
              const groupModels = models.filter(
                (model) => normalizeTier(model.tier) === group.tier,
              );
              if (groupModels.length === 0) return null;
              return (
                <SelectGroup key={group.label}>
                  <SelectLabel>{group.label}</SelectLabel>
                  {groupModels.map((model) => renderModelItem(model, true))}
                </SelectGroup>
              );
            })
          ) : (
            models.map((model) => renderModelItem(model, false))
          )
        ) : (
          <div className="px-2 py-1.5 text-sm text-muted">暂无可用模型</div>
        )}
      </SelectContent>
    </Select>
  );
}
