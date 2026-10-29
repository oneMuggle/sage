import type { CandidateModel } from '../../entities/model-catalog/types';

/**
 * `discoveredModels[].id` 未必等于 catalog 的 `model_key.model_id`: OpenRouter
 * 风格端点报 `openai/gpt-4o`, catalog 可能存裸 slug (反之亦然); 同一裸 id 还可能
 * 在多个 provider / pricing_scope 下各有一条。两种情形都不能猜 —— 猜错等于把
 * A 端点的价格和上下文窗口套到 B 端点的模型上。
 *
 * 解析规则与后端 `discovery_ingest._CatalogIndex.resolve` (R34b) 保持一致:
 * 1. 精确命中且唯一 → 用它
 * 2. 否则 catalog id 以 `/<discoveredId>` 结尾且唯一 → 用它
 * 3. 其余 (0 条或歧义) → null, 调用方按「未分类」渲染
 */
export type CatalogEnricher = (discoveredId: string) => CandidateModel | null;

function identityOf(item: CandidateModel): string {
  return JSON.stringify([item.model_key.provider, item.model_key.model_id, item.pricing_scope]);
}

function onlyOne(bucket: Map<string, CandidateModel> | undefined): CandidateModel | null {
  if (!bucket || bucket.size !== 1) return null;
  const first = bucket.values().next();
  return first.done ? null : first.value;
}

export function buildCatalogEnricher(items: readonly CandidateModel[]): CatalogEnricher {
  const byModelId = new Map<string, Map<string, CandidateModel>>();
  for (const item of items) {
    const modelId = item.model_key.model_id;
    const bucket = byModelId.get(modelId);
    if (bucket) {
      bucket.set(identityOf(item), item);
    } else {
      byModelId.set(modelId, new Map([[identityOf(item), item]]));
    }
  }

  return (discoveredId) => {
    // 精确层一旦命中就直接定论: 歧义也是定论（不富化），不再到后缀层碰运气。
    const exactBucket = byModelId.get(discoveredId);
    if (exactBucket) return onlyOne(exactBucket);

    const suffix = `/${discoveredId}`;
    const matches = new Map<string, CandidateModel>();
    for (const [modelId, bucket] of byModelId) {
      if (!modelId.endsWith(suffix)) continue;
      for (const [key, item] of bucket) matches.set(key, item);
    }
    return onlyOne(matches);
  };
}
