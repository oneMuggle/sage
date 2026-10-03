/**
 * IPC contract helpers — a pure module (type-only import, no runtime dependencies) so that it
 * runs under vitest and is evaluated by scripts/export-ipc-manifest.mjs without a bundler.
 *
 * COMMAND_ROUTES maps renderer `invoke(cmd)` names to backend HTTP routes through `path()`
 * functions. The contract tests need those routes as DATA: which (method, path) does each
 * command hit? `buildIpcManifest` evaluates every `path()` against a probe `args` object that
 * answers any property with a marker string, then turns the markers into `{name}` placeholders.
 */
import type { CommandRoute } from './commands';

interface IpcManifestEntry {
  method: CommandRoute['method'];
  /** Path template without query string; dynamic segments are written `{argName}`. */
  path: string;
}

export type IpcManifest = Record<string, IpcManifestEntry>;

// Markers use only [A-Za-z0-9_], so `encodeURIComponent(String(args.x))` leaves them intact.
const MARK_OPEN = 'ARGx_';
const MARK_CLOSE = '_xARG';
const MARK_RE = /ARGx_(.+?)_xARG/g;

/** An `args` stand-in: every property reads as a marker and `in` is always true. */
function probeArgs(): Record<string, unknown> {
  return new Proxy(
    {},
    {
      get: (_target, prop) =>
        typeof prop === 'string' ? `${MARK_OPEN}${prop}${MARK_CLOSE}` : undefined,
      has: () => true,
    },
  ) as Record<string, unknown>;
}

/** Drop the query string and turn arg markers into `{name}` placeholders. */
function normalizeRoutePath(raw: string): string {
  const q = raw.indexOf('?');
  return (q === -1 ? raw : raw.slice(0, q)).replace(MARK_RE, '{$1}');
}

/** Evaluate every route's `path()` once and return a key-sorted (method, path template) table. */
export function buildIpcManifest(routes: Record<string, CommandRoute>): IpcManifest {
  const manifest: IpcManifest = {};
  for (const cmd of Object.keys(routes).sort()) {
    const route = routes[cmd];
    let raw: string;
    try {
      raw = route.path(probeArgs());
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`ipc manifest: cannot evaluate path() of "${cmd}": ${reason}`);
    }
    manifest[cmd] = { method: route.method, path: normalizeRoutePath(raw) };
  }
  return manifest;
}
