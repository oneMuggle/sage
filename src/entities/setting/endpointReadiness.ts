import type { EndpointConfig } from './types';

<<<<<<< HEAD
/** One protocol-aware rule shared by onboarding and connection indicators. */
export function isEndpointConfigured(
  endpoint: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null | undefined,
): boolean {
  if (!endpoint || typeof endpoint.baseUrl !== 'string' || !endpoint.baseUrl.trim()) return false;
  return (
    endpoint.protocol === 'ollama' ||
    (typeof endpoint.apiKey === 'string' && endpoint.apiKey.trim().length > 0)
  );
=======
/**
 * Readiness input. `hasApiKey` is the backend's redaction marker: the real
 * credential is never returned by GET /settings, so a frontend that lost its
 * local cache only has this flag to prove a key exists.
 */
type EndpointReadinessInput = Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> & {
  hasApiKey?: boolean;
};

function hasAvailableApiKey(endpoint: EndpointReadinessInput): boolean {
  if (typeof endpoint.apiKey === 'string' && endpoint.apiKey.trim().length > 0) return true;
  return endpoint.hasApiKey === true;
}

/**
 * One protocol-aware rule shared by onboarding and connection indicators.
 *
 * A key counts as present when the local text is non-empty OR when the
 * backend reports `hasApiKey: true` — otherwise any profile whose settings
 * cache was lost (different dev origin/worktree, cleared storage) would be
 * treated as unconfigured although chat works fine server-side.
 */
export function isEndpointConfigured(endpoint: EndpointReadinessInput | null | undefined): boolean {
  if (!endpoint || typeof endpoint.baseUrl !== 'string' || !endpoint.baseUrl.trim()) return false;
  return endpoint.protocol === 'ollama' || hasAvailableApiKey(endpoint);
>>>>>>> origin/main
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
<<<<<<< HEAD
  endpoint?: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null,
=======
  endpoint?: EndpointReadinessInput | null,
>>>>>>> origin/main
): EndpointReadinessAuditSnapshot {
  const configured = isEndpointConfigured(endpoint);
  const protocol =
    endpoint && typeof endpoint.protocol === 'string' && endpoint.protocol.trim().length > 0
      ? endpoint.protocol.trim()
      : null;
  const hasBaseUrl = Boolean(
    endpoint && typeof endpoint.baseUrl === 'string' && endpoint.baseUrl.trim().length > 0,
  );
<<<<<<< HEAD
  const hasApiKey = Boolean(
    endpoint && typeof endpoint.apiKey === 'string' && endpoint.apiKey.trim().length > 0,
  );
=======
  // Reflect availability, not just the local text: hasApiKey=true means the
  // credential lives in the backend and chat can still use it.
  const hasApiKey = Boolean(endpoint && hasAvailableApiKey(endpoint));
>>>>>>> origin/main
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

<<<<<<< HEAD
export function buildEndpointReadinessAuditJson(
  endpoint?: Pick<EndpointConfig, 'baseUrl' | 'apiKey' | 'protocol'> | null,
): string {
=======
export function buildEndpointReadinessAuditJson(endpoint?: EndpointReadinessInput | null): string {
>>>>>>> origin/main
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
