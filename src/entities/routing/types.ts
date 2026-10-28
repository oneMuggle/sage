import type { EffectiveModel } from '../model-catalog/types';

export type Tier = 'fast' | 'balanced' | 'powerful';

export interface RoutingPreference {
  preferred_tier?: Tier | null;
  /** 锁定的模型对象；后端直接把它当作 selected_model 返回（非 model id 字符串）。 */
  locked_model?: EffectiveModel | null;
}

export interface RouteRequest {
  task_type: string;
  context_length: number;
  required_capabilities: string[];
  user_preference?: RoutingPreference | null;
  endpoint_id?: string | null;
}

export interface RouteResponse {
  selected_model: EffectiveModel;
  reason: string;
  alternatives: EffectiveModel[];
}
