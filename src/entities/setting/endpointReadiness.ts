import type { EndpointConfig } from './types';

/** One protocol-aware rule shared by onboarding and connection indicators. */
export function isEndpointConfigured(
  endpoint: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null | undefined,
): boolean {
  if (!endpoint || typeof endpoint.baseUrl !== 'string' || !endpoint.baseUrl.trim()) return false;
  return (
    endpoint.protocol === 'ollama' ||
    (typeof endpoint.apiKey === 'string' && endpoint.apiKey.trim().length > 0)
  );
}
