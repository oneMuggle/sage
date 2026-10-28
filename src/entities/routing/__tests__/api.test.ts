import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const backendRequest = vi.hoisted(() => vi.fn());

vi.mock('../../../shared/api/backendRequest', () => ({ backendRequest }));

import type { EffectiveModel } from '../../model-catalog/types';
import { routeModel } from '../api';

describe('routing API client', () => {
  beforeEach(() => {
    backendRequest.mockResolvedValue({ selected_model: {}, reason: 'r', alternatives: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('posts the full routing request to /api/v1/routing/route', async () => {
    await routeModel({
      task_type: 'code_generation',
      context_length: 8000,
      required_capabilities: ['chat'],
      endpoint_id: 'ep-a',
      user_preference: { preferred_tier: 'balanced' },
    });

    expect(backendRequest).toHaveBeenCalledWith({
      path: '/api/v1/routing/route',
      method: 'POST',
      body: {
        task_type: 'code_generation',
        context_length: 8000,
        required_capabilities: ['chat'],
        endpoint_id: 'ep-a',
        user_preference: { preferred_tier: 'balanced' },
      },
    });
  });

  it('omits unset optional fields instead of sending nulls', async () => {
    await routeModel({ task_type: 'chat', context_length: 4096, required_capabilities: [] });

    const argument = backendRequest.mock.calls[0][0];
    expect(argument.body).toEqual({
      task_type: 'chat',
      context_length: 4096,
      required_capabilities: [],
    });
    expect('endpoint_id' in argument.body).toBe(false);
    expect('user_preference' in argument.body).toBe(false);
  });

  it('omits explicit null optionals', async () => {
    await routeModel({
      task_type: 'chat',
      context_length: 4096,
      required_capabilities: [],
      endpoint_id: null,
      user_preference: null,
    });

    const argument = backendRequest.mock.calls[0][0];
    expect('endpoint_id' in argument.body).toBe(false);
    expect('user_preference' in argument.body).toBe(false);
  });

  it('treats an empty endpoint_id as unset rather than scoping to ""', async () => {
    await routeModel({
      task_type: 'chat',
      context_length: 4096,
      required_capabilities: [],
      endpoint_id: '',
    });

    const argument = backendRequest.mock.calls[0][0];
    expect('endpoint_id' in argument.body).toBe(false);
  });

  it('forwards a locked model object unchanged', async () => {
    const locked: EffectiveModel = {
      model_key: { provider: 'anthropic', model_id: 'claude-3-opus' },
      tier: 'powerful',
      limits: { native: 200000, service: null },
      price: { input_per_million: '15.00', output_per_million: '75.00', currency: 'USD' },
      provenance: {},
      revision: 1,
    };

    await routeModel({
      task_type: 'chat',
      context_length: 4096,
      required_capabilities: [],
      user_preference: { locked_model: locked },
    });

    const argument = backendRequest.mock.calls[0][0];
    expect(argument.body.user_preference).toEqual({ locked_model: locked });
  });
});
