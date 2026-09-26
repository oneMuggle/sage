// 对话阅读体验第二轮 C3：端点可达性判定与状态。
import { beforeEach, describe, expect, it } from 'vitest';

import {
  classifyEndpointError,
  hostOf,
  isSameEndpoint,
  reportStreamFailure,
  reportStreamSuccess,
  useEndpointStatusStore,
} from '../endpointStatus';

beforeEach(() => {
  useEndpointStatusStore.setState({ issue: null, dismissed: false });
});

describe('classifyEndpointError', () => {
  it('treats network failures, timeouts and gateway errors as unreachable', () => {
    expect(classifyEndpointError({ type: 'network_error', message: 'ECONNREFUSED' })).toEqual({
      kind: 'network',
      status: null,
      message: 'ECONNREFUSED',
    });
    expect(classifyEndpointError({ type: 'timeout', message: 't' })?.kind).toBe('timeout');
    expect(classifyEndpointError({ type: 'server_error', status_code: 503 })).toEqual({
      kind: 'server',
      status: 503,
      message: '',
    });
  });

  it('ignores other failures', () => {
    expect(classifyEndpointError({ type: 'server_error', status_code: 500 })).toBeNull();
    expect(classifyEndpointError({ type: 'auth_failed', status_code: 401 })).toBeNull();
    expect(classifyEndpointError({ type: 'rate_limited' })).toBeNull();
    expect(classifyEndpointError('max_iterations_exceeded')).toBeNull();
    expect(classifyEndpointError(undefined)).toBeNull();
  });
});

describe('endpoint helpers', () => {
  it('extracts hosts and compares endpoints loosely', () => {
    expect(hostOf('https://api.example.com/v1')).toBe('api.example.com');
    expect(hostOf('not a url')).toBeNull();
    expect(isSameEndpoint('https://API.example.com/v1/', 'https://api.example.com/v1')).toBe(true);
    expect(isSameEndpoint('https://a.test/v1', 'https://b.test/v1')).toBe(false);
    expect(isSameEndpoint(null, 'https://b.test/v1')).toBe(false);
  });
});

describe('stream reporting', () => {
  it('records the endpoint of a failed stream and clears it after a success', () => {
    reportStreamFailure(
      { type: 'network_error', message: 'connect failed' },
      { apiUrl: 'https://api.example.com/v1', model: 'gpt-test' },
    );
    const issue = useEndpointStatusStore.getState().issue;
    expect(issue).toMatchObject({
      kind: 'network',
      baseUrl: 'https://api.example.com/v1',
      host: 'api.example.com',
      model: 'gpt-test',
      message: 'connect failed',
    });

    reportStreamSuccess();
    expect(useEndpointStatusStore.getState().issue).toBeNull();
  });

  it('keeps the state for unrelated failures and re-shows a dismissed notice on a new failure', () => {
    reportStreamFailure({ type: 'auth_failed', status_code: 401 });
    expect(useEndpointStatusStore.getState().issue).toBeNull();

    reportStreamFailure({ type: 'timeout' }, { apiUrl: 'https://a.test/v1' });
    useEndpointStatusStore.getState().dismiss();
    expect(useEndpointStatusStore.getState().dismissed).toBe(true);
    reportStreamFailure({ type: 'timeout' }, { apiUrl: 'https://a.test/v1' });
    expect(useEndpointStatusStore.getState().dismissed).toBe(false);
  });
});
