/**
 * Domain route tables merged into COMMAND_ROUTES (electron/commands.ts).
 *
 * New IPC commands go into a domain file in this directory, not into commands.ts: that file is
 * the repo's most conflict-prone one, and the #857 regression (13 commands silently dropped when
 * a stale branch merged over it) came from exactly that. Each domain file exports a
 * `Record<string, CommandRoute>`; list it in DOMAIN_ROUTES below.
 *
 * Rules (enforced by electron/__tests__/ipc-contract.test.ts):
 *  - keys are unique across commands.ts and every file here — a later spread would otherwise
 *    silently override an earlier one;
 *  - files stay pure: relative imports only, so scripts/export-ipc-manifest.mjs can evaluate
 *    them without a bundler.
 */
import type { CommandRoute } from '../commands';
import { promptRoutes } from './prompts';

export const DOMAIN_ROUTES: Record<string, CommandRoute> = {
  ...promptRoutes,
};
