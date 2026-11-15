/**
 * 对话模型的实际生效选择 —— 全局选择 + 会话级覆盖。
 *
 * 会话级模型覆盖（SessionModelPicker / backend `session_model_overrides`）
 * 优先于全局 `modelSelections.chatModel`。聊天页的视觉能力判定、请求凭据
 * 与 `ChatRequest.model` 必须使用同一份解析结果，否则会出现：
 * - 会话已切到多模态模型，输入框仍按全局文本模型显示「不支持视觉」；
 * - 覆盖模型与全局模型落在同一端点时，旧逻辑因「端点不变」而丢弃覆盖，
 *   请求仍按全局模型发出。
 */

import type { EndpointConfig, ModelSelection } from '../../entities/setting/types';

/** 会话模型覆盖变更事件（SessionModelPicker / Welcome 写入后广播）。 */
export const SESSION_MODEL_OVERRIDE_EVENT = 'sage:session-model-override-changed';

export interface SessionModelOverrideDetail {
  sessionId: string;
  modelId: string | null;
}

export interface EffectiveChatModel {
  /** 实际生效模型所属端点；未选择时为 undefined。 */
  endpoint: EndpointConfig | undefined;
  /** 实际生效模型 id；未选择时为空串。 */
  modelId: string;
}

/**
 * 在端点列表里找到提供指定模型的端点。
 *
 * 优先选择带 apiKey 的端点（同名模型可能被多个端点提供）。
 */
export function findEndpointForModel(
  modelId: string,
  endpoints: readonly EndpointConfig[],
): EndpointConfig | undefined {
  if (!modelId || !endpoints?.length) return undefined;
  const candidates = endpoints.filter((endpoint) =>
    (endpoint.discoveredModels ?? []).some((model) => model.id === modelId),
  );
  if (candidates.length === 0) return undefined;
  return candidates.find((endpoint) => endpoint.apiKey) ?? candidates[0];
}

/**
 * 解析实际生效的对话模型。
 *
 * @param selection 全局 `modelSelections.chatModel`。
 * @param endpoints 当前全部端点配置。
 * @param sessionOverride 会话级模型覆盖；null/undefined 表示跟随全局。
 * @returns 实际生效的端点与模型 id。覆盖模型在端点列表中找不到时回退全局
 *   （fail-open：宁可按全局模型发请求，也不把「未知覆盖」变成空选择）。
 */
export function resolveEffectiveChatModel(
  selection: ModelSelection,
  endpoints: readonly EndpointConfig[],
  sessionOverride?: string | null,
): EffectiveChatModel {
  const globalModelId = selection.modelId ?? '';
  const globalEndpoint = selection.endpointId
    ? endpoints.find((endpoint) => endpoint.id === selection.endpointId)
    : undefined;

  const override = (sessionOverride ?? '').trim();
  if (!override || override === globalModelId) {
    return { endpoint: globalEndpoint, modelId: globalModelId };
  }

  const owningEndpoint = findEndpointForModel(override, endpoints);
  if (!owningEndpoint) {
    return { endpoint: globalEndpoint, modelId: globalModelId };
  }

  // 覆盖模型可能与全局模型在同一端点：端点不变，但模型 id 必须替换。
  return { endpoint: owningEndpoint, modelId: override };
}

/** 广播会话模型覆盖变更，供 ChatInput 等只读消费方刷新判定。 */
export function emitSessionModelOverrideChanged(detail: SessionModelOverrideDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<SessionModelOverrideDetail>(SESSION_MODEL_OVERRIDE_EVENT, { detail }));
}

/** 订阅会话模型覆盖变更；返回取消订阅函数（SSR / 测试环境安全）。 */
export function subscribeSessionModelOverrideChanged(
  handler: (detail: SessionModelOverrideDetail) => void,
): () => void {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: Event) => {
    handler((event as CustomEvent<SessionModelOverrideDetail>).detail);
  };
  window.addEventListener(SESSION_MODEL_OVERRIDE_EVENT, listener);
  return () => window.removeEventListener(SESSION_MODEL_OVERRIDE_EVENT, listener);
}
