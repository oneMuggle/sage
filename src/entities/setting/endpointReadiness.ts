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

export interface EndpointReadinessAuditSnapshot {
  configured: boolean;
  protocol: string | null;
  hasBaseUrl: boolean;
  hasApiKey: boolean;
  requiresApiKey: boolean;
  signature: string;
}

export function buildEndpointReadinessAuditSnapshot(
  endpoint?: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null,
): EndpointReadinessAuditSnapshot {
  const configured = isEndpointConfigured(endpoint);
  const protocol =
    endpoint && typeof endpoint.protocol === 'string' && endpoint.protocol.trim().length > 0
      ? endpoint.protocol.trim()
      : null;
  const hasBaseUrl = Boolean(
    endpoint && typeof endpoint.baseUrl === 'string' && endpoint.baseUrl.trim().length > 0,
  );
  const hasApiKey = Boolean(
    endpoint && typeof endpoint.apiKey === 'string' && endpoint.apiKey.trim().length > 0,
  );
  const requiresApiKey = protocol !== 'ollama';
  const signature = `${configured ? 1 : 0}|${protocol ?? '-'}|${hasBaseUrl ? 1 : 0}|${hasApiKey ? 1 : 0}|${requiresApiKey ? 1 : 0}`;
  return {
    configured,
    protocol,
    hasBaseUrl,
    hasApiKey,
    requiresApiKey,
    signature,
  };
}

export function buildEndpointReadinessAuditJson(
  endpoint?: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null,
): string {
  return JSON.stringify(buildEndpointReadinessAuditSnapshot(endpoint), null, 2);
}
