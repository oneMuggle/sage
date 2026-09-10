/**
 * Renderer-side feature flag for the pluggable update providers UI.
 *
 * Mirrors the main-process `electron/update/featureFlag.ts` shape:
 *   - dev mode (Vite) → ON
 *   - prod → OFF unless explicitly enabled via window.__ENABLE_PROVIDERS__ = true
 *
 * The window escape hatch is set by main via webPreferences.additionalArguments
 * when SAGE_EXPERIMENTAL_PROVIDERS=1 is in env, so a packaged debug build can
 * still flip it without a rebuild. The flag is read once at module load.
 */
declare global {
  interface Window {
    __ENABLE_PROVIDERS__?: boolean;
  }
}

export const ENABLE_UPDATE_PROVIDERS_UI = (): boolean => {
  if (import.meta.env.DEV) return true;
  return typeof window !== 'undefined' && window.__ENABLE_PROVIDERS__ === true;
};