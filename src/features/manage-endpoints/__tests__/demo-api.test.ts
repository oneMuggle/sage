import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockIsDemoMode = vi.fn();

vi.mock('../../../shared/api/demoInterceptors', () => ({
  isDemoMode: () => mockIsDemoMode(),
}));

import { fetchModels, testEndpointConnection } from '../api';

const originalFetch = globalThis.fetch;

beforeEach(() => {
  mockIsDemoMode.mockReset();
  mockIsDemoMode.mockReturnValue(true);
  globalThis.fetch = vi.fn() as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('endpoint APIs in demo mode', () => {
  it('returns demo models without making a network request', async () => {
    await expect(fetchModels('https://real.example/v1', 'secret-key')).resolves.toEqual([
      expect.objectContaining({ id: 'qwen2.5-14b-instruct' }),
      expect.objectContaining({ id: 'bge-m3' }),
    ]);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('returns a successful demo connection result without exposing or using credentials', async () => {
    const result = await testEndpointConnection('https://real.example/v1', 'secret-key');

    expect(result).toMatchObject({ success: true, latency: 0 });
    expect(result.message).toContain('未发送网络请求');
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});
