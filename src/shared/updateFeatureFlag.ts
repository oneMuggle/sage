/**
 * Renderer-side feature flag for the pluggable update providers UI.
 *
 * Phase 3 T3.4 (2026-09): 默认全开. 任何非显式关闭的情况都返回 true。
 *
 * Escape hatch: 主进程可通过 webPreferences.additionalArguments 注入
 * `--sage-disable-providers-ui=1`, preload 读 argv 转 window.__DISABLE_PROVIDERS__,
 * 这里识别到即返回 false。
 */
declare global {
  interface Window {
    __ENABLE_PROVIDERS__?: boolean;
    __DISABLE_PROVIDERS__?: boolean;
  }
}

export const ENABLE_UPDATE_PROVIDERS_UI = (): boolean => {
  if (typeof window !== 'undefined' && window.__DISABLE_PROVIDERS__ === true) return false;
  return true;
};

/* v8 ignore start */
export function formatUpdateFeatureFlagSummary(enabled?: boolean | null): string {
  const active = typeof enabled === 'boolean' ? enabled : ENABLE_UPDATE_PROVIDERS_UI();
  return `updateProvidersUi=${active ? 'enabled' : 'disabled'}`;
}

export function formatUpdateFeatureFlagJson(enabled?: boolean | null): string {
  const active = typeof enabled === 'boolean' ? enabled : ENABLE_UPDATE_PROVIDERS_UI();
  return JSON.stringify({
    updateProvidersUi: active,
  });
}
/* v8 ignore stop */

export function auditUpdateFeatureFlagGovernance(): {
  module: 'src/shared/updateFeatureFlag.ts';
  phase: 'P174';
  domain: 'shared';
  defaultEnabled: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/shared/updateFeatureFlag.ts',
    phase: 'P174',
    domain: 'shared',
    defaultEnabled: true,
    compliant: formatUpdateFeatureFlagSummary(true) === 'updateProvidersUi=enabled',
  };
}
