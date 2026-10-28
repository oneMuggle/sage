import type { EffectiveModel } from '../model-catalog/types';

export type Tier = 'fast' | 'balanced' | 'powerful';

export interface RoutingPreference {
  preferred_tier?: Tier | null;
  locked_model?: string | null;
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
