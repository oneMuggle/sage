/**
 * Display-mode predicates shared by the main process and tests.
 *
 * `in-app` uses a corner dock inside the main window; `both` shows the
 * desktop overlay and the in-app dock. `off` disables everything.
 */

import type { PetConfig } from './types';

export function shouldShowDesktop(config: PetConfig): boolean {
  return config.enabled && (config.displayMode === 'desktop' || config.displayMode === 'both');
}

export function shouldShowInApp(config: PetConfig): boolean {
  return config.enabled && (config.displayMode === 'in-app' || config.displayMode === 'both');
}
