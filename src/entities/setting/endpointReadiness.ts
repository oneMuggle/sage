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

export function auditEndpointReadinessGovernance(
  state: {
    configuredCount?: number;
    enabledCount?: number;
  } = {},
): {
  module: 'src/entities/setting/endpointReadiness.ts';
  phase: 'P155';
  configuredCount: number;
  enabledCount: number;
  healthy: boolean;
} {
  const configuredCount =
    typeof state.configuredCount === 'number' && Number.isFinite(state.configuredCount)
      ? Math.max(0, Math.trunc(state.configuredCount))
      : 1;
  const enabledCount =
    typeof state.enabledCount === 'number' && Number.isFinite(state.enabledCount)
      ? Math.max(0, Math.trunc(state.enabledCount))
      : 1;
  return {
    module: 'src/entities/setting/endpointReadiness.ts',
    phase: 'P155',
    configuredCount,
    enabledCount,
    healthy: configuredCount >= 1 && enabledCount >= 1,
  };
}
