import { backendRequest } from '../../shared/api/backendRequest';

import type { RouteRequest, RouteResponse } from './types';

const PATH = '/api/v1/routing/route';

/** Ask the backend which model should serve this task on this endpoint. */
export async function routeModel(request: RouteRequest): Promise<RouteResponse> {
  const body: Record<string, unknown> = {
    task_type: request.task_type,
    context_length: request.context_length,
    required_capabilities: request.required_capabilities,
  };
  if (request.endpoint_id !== undefined && request.endpoint_id !== null) {
    body.endpoint_id = request.endpoint_id;
  }
  if (request.user_preference !== undefined && request.user_preference !== null) {
    body.user_preference = request.user_preference;
  }
  return backendRequest<RouteResponse>({ path: PATH, method: 'POST', body });
}
