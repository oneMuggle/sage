/**
 * 视觉能力分层解析 —— 把"模型是否支持 vision"判定从单一启发式提升到分层权威源。
 *
 * 优先级（自上而下，首次命中即返回）：
 *
 *   1. model-catalog `user_override` / `service_probe` / `imported_snapshot` / `builtin`
 *      合并后的 `EffectiveModel.capabilities.vision`
 *      - `true`  → `'supported'`
 *      - `false` → `'unsupported'`
 *      - `null` / `undefined` / 字段缺失 → 进入 2.
 *   2. `endpoint.discoveredModels.find(m => m.id === modelId)?.capabilities`
 *      - 命中 + 含 `'vision'` → `'supported'`
 *      - 命中 + 不含 `'vision'` → `'unsupported'`（启发式窄推断的遗留）
 *      - 未命中 → `'unknown'`
 *
 * 消费方（`ChatInput.tsx` / `useChat.ts`）语义：
 * - `'unsupported'` → 显示警告 / 剔除 `'vision'`
 * - `'supported' | 'unknown'` → 不显示警告 / 保留 `'vision'`
 *
 * 这与后端 `backend/core/legacy/agent.py:960-964` 的 fail-safe
 * "未知视为支持 vision" 完全对齐，消除当前"前端禁用、后端其实能处理"的割裂。
 */

import type { EffectiveModel } from '../../entities/model-catalog/types';
import type { EndpointConfig } from '../../entities/setting/types';

export type VisionSupport = 'supported' | 'unsupported' | 'unknown';

/**
 * 解析当前 chatModel 的视觉能力。
 *
 * @param endpoint 当前 chatModel 所在端点；null / undefined 直接返回 `'unknown'`。
 * @param modelId 当前 chatModel 的 modelId；null / undefined / 空串返回 `'unknown'`。
 * @param catalog model-catalog effective 解析结果（可选）。`null` / `undefined`
 *   表示 catalog 不可用（离线 / 404 / 网络失败），跳过第一层直接走 discoveredModels 回退。
 */
export function resolveVisionSupport(
  endpoint: EndpointConfig | null | undefined,
  modelId: string | null | undefined,
  catalog?: EffectiveModel | null,
): VisionSupport {
  if (!modelId || !endpoint) {
    return 'unknown';
  }

  // 1. catalog 层 —— 权威
  if (catalog?.capabilities && typeof catalog.capabilities === 'object') {
    const vision = catalog.capabilities.vision;
    if (vision === true) return 'supported';
    if (vision === false) return 'unsupported';
    // null / undefined → 落回下一层
  }

  // 2. discoveredModels 回退 —— 启发式（来自端点 /v1/models 发现时的推断）
  const discovered = endpoint.discoveredModels?.find((m) => m.id === modelId);
  if (!discovered) {
    // 模型不在发现列表（端点未测试 / 模型是手动填入的）→ 未知
    return 'unknown';
  }
  const caps = discovered.capabilities ?? [];
  return caps.includes('vision') ? 'supported' : 'unsupported';
}

/**
 * 把 `VisionSupport` 映射为发给后端 `ChatRequest.capabilities` 的数组。
 *
 * - `'unsupported'` → `['chat']`（后端据此触发 visionModel / OCR 路径）
 * - `'supported' | 'unknown'` → `['chat', 'vision']`（后端按原生多模态处理）
 *
 * 与后端 `legacy_routes.py:836-847` 的 frontend-overrides-backend 协议对齐：
 * 后端只在 `capabilities` 里**不含** `'vision'` 时才走 fallback；含 `'vision'`
 * 即按原生多模态处理（与 `agent.py` fail-safe 一致）。
 */
export function toRequestCapabilities(support: VisionSupport): string[] {
  return support === 'unsupported' ? ['chat'] : ['chat', 'vision'];
}
