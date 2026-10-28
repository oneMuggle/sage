import { backendRequest } from '../../shared/api/backendRequest';

import type { RouteRequest, RouteResponse } from './types';

const PATH = '/api/v1/routing/route';

/**
 * 请后端为「该端点上、这类任务」挑选模型。
 *
 * 未设置的可选项不下发：`endpoint_id` 用真值判断，空串视为"不限定端点"
 * （与 `model-catalog/api.ts` 的 `if (params.endpointId)` 口径一致），
 * 否则后端会按 `WHERE endpoint_id = ''` 查到空集并返回 422。
 */
export async function routeModel(request: RouteRequest): Promise<RouteResponse> {
  const body: Record<string, unknown> = {
    task_type: request.task_type,
    context_length: request.context_length,
    required_capabilities: request.required_capabilities,
  };
  if (request.endpoint_id) {
    body.endpoint_id = request.endpoint_id;
  }
  if (request.user_preference !== undefined && request.user_preference !== null) {
    body.user_preference = request.user_preference;
  }
  return backendRequest<RouteResponse>({ path: PATH, method: 'POST', body });
}
