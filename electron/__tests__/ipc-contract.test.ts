// @vitest-environment node
/**
 * IPC contract gate — docs/plans/2026-10-02_ui-feature-logic-optimization-followup.md §L1.
 *
 * Three layers each test only their own side: the renderer tests stub `invoke`, the electron
 * tests check the shape of the route table, the backend tests call routes directly. Nothing
 * verified that the layers line up — #857 silently dropped 13 commands the renderer still calls
 * and CI stayed green. This file is the missing middle:
 *
 *   T1  every command the renderer invokes is handled by the main process (COMMAND_ROUTES, or a
 *       streaming command that main.ts special-cases before it falls through to invokeBackend),
 *       or is listed in ipc-known-gaps.json. The committed manifest must match COMMAND_ROUTES.
 *   T3  command keys are unique across commands.ts and electron/commandRoutes/*.
 *   T2  (backend/tests/contract/test_ipc_manifest_routes.py) every manifest route exists in the
 *       real FastAPI app.
 *
 * ipc-known-gaps.json only ever shrinks: a NEW gap fails, and so does an entry that is no longer
 * a gap — delete it in the PR that fixes it.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

import { COMMAND_ROUTES, type CommandRoute } from '../commands';
import { buildIpcManifest, type IpcManifest } from '../ipcManifest';

const REPO_ROOT = resolve(__dirname, '..', '..');
const readRepo = (rel: string): string => readFileSync(join(REPO_ROOT, rel), 'utf-8');

interface KnownGaps {
  frontendUnregistered: Record<string, string[]>;
  manifestWithoutRoute: string[];
}
const knownGaps = JSON.parse(readRepo('electron/ipc-known-gaps.json')) as KnownGaps;
const knownUnregistered = new Set(Object.values(knownGaps.frontendUnregistered).flat());

// ── source discovery ────────────────────────────────────────────────────────────────────────

const isTestFile = (rel: string): boolean =>
  /(^|\/)(__tests__|__mocks__)\//.test(rel) ||
  /\.(test|spec)\.[cm]?[jt]sx?$/.test(rel) ||
  /(^|\/)test-setup\.ts$/.test(rel);

function listSources(dirRel: string, out: string[] = []): string[] {
  for (const name of readdirSync(join(REPO_ROOT, dirRel))) {
    const rel = `${dirRel}/${name}`;
    if (statSync(join(REPO_ROOT, rel)).isDirectory()) {
      if (name !== 'node_modules') listSources(rel, out);
    } else if (/\.tsx?$/.test(name) && !isTestFile(rel)) {
      out.push(rel);
    }
  }
  return out;
}

function parse(rel: string, text: string): ts.SourceFile {
  const kind = rel.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, kind);
}

const literalText = (n: ts.Node | undefined): string | null =>
  n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) ? n.text : null;

// ── T1 inputs ───────────────────────────────────────────────────────────────────────────────

type Fn = ts.FunctionDeclaration | ts.ArrowFunction | ts.FunctionExpression;

/**
 * Commands the renderer invokes with a literal name: `invoke('x')` / `invoke<T>('x', …)`,
 * including calls through a same-file wrapper that forwards its first parameter to `invoke`
 * (e.g. settingsClient's `ipcCall(cmd)`). Wrappers exported to other files are not followed.
 */
function scanRendererInvokes(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const rel of listSources('src')) {
    const text = readRepo(rel);
    if (!text.includes('invoke')) continue;
    const sf = parse(rel, text);

    const callees = new Set<string>(['invoke']);
    for (const stmt of sf.statements) {
      if (
        ts.isImportDeclaration(stmt) &&
        ts.isStringLiteral(stmt.moduleSpecifier) &&
        /desktopInvoke$/.test(stmt.moduleSpecifier.text)
      ) {
        const bindings = stmt.importClause?.namedBindings;
        if (bindings && ts.isNamedImports(bindings)) {
          for (const el of bindings.elements) {
            if ((el.propertyName ?? el.name).text === 'invoke') callees.add(el.name.text);
          }
        }
      }
    }
    const isInvoke = (e: ts.Expression): boolean =>
      (ts.isIdentifier(e) && callees.has(e.text)) ||
      (ts.isPropertyAccessExpression(e) && e.name.text === 'invoke');

    const wrappers = new Set<string>();
    const findWrappers = (n: ts.Node): void => {
      let name: string | undefined;
      let fn: Fn | undefined;
      if (ts.isFunctionDeclaration(n) && n.name) {
        name = n.name.text;
        fn = n;
      } else if (
        ts.isVariableDeclaration(n) &&
        ts.isIdentifier(n.name) &&
        n.initializer &&
        (ts.isArrowFunction(n.initializer) || ts.isFunctionExpression(n.initializer))
      ) {
        name = n.name.text;
        fn = n.initializer;
      }
      const param = fn?.parameters[0]?.name;
      if (name && fn?.body && param && ts.isIdentifier(param)) {
        const forwards = (c: ts.Node): boolean | undefined => {
          const first = ts.isCallExpression(c) ? c.arguments[0] : undefined;
          if (first && ts.isIdentifier(first) && first.text === param.text) {
            if (ts.isCallExpression(c) && isInvoke(c.expression)) return true;
          }
          return ts.forEachChild(c, forwards);
        };
        if (forwards(fn.body)) wrappers.add(name);
      }
      ts.forEachChild(n, findWrappers);
    };
    findWrappers(sf);

    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n)) {
        const callee = n.expression;
        const viaWrapper = ts.isIdentifier(callee) && wrappers.has(callee.text);
        if (isInvoke(callee) || viaWrapper) {
          const name = literalText(n.arguments[0]);
          if (name !== null) {
            const { line } = sf.getLineAndCharacterOfPosition(n.getStart(sf));
            const where = `${rel}:${line + 1}`;
            const list = used.get(name);
            if (list) list.push(where);
            else used.set(name, [where]);
          }
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return used;
}

/**
 * Commands the `sage:invoke` handler in electron/main.ts dispatches itself (streaming relays)
 * before it falls through to invokeBackend(COMMAND_ROUTES). They are handled, just not routed.
 */
function mainProcessSpecialCommands(): string[] {
  const main = readRepo('electron/main.ts');
  const start = main.search(/ipcMain\.handle\(\s*'sage:invoke'/);
  const end = start === -1 ? -1 : main.indexOf('invokeBackend(', start);
  if (start === -1 || end === -1) {
    throw new Error(
      "ipc-contract: cannot locate the 'sage:invoke' handler in electron/main.ts. " +
        'If the dispatcher was refactored, update mainProcessSpecialCommands().',
    );
  }
  return [...main.slice(start, end).matchAll(/\bcmd\s*===\s*'([A-Za-z0-9_]+)'/g)].map((m) => m[1]);
}

// ── T3 input ────────────────────────────────────────────────────────────────────────────────

/** Keys of every route entry (an object literal with `method` and `path`) defined in a file. */
function routeEntryKeys(rel: string): string[] {
  const keys: string[] = [];
  const has = (o: ts.ObjectLiteralExpression, name: string): boolean =>
    o.properties.some(
      (p) =>
        p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === name,
    );
  const visit = (n: ts.Node): void => {
    if (
      ts.isPropertyAssignment(n) &&
      (ts.isIdentifier(n.name) || ts.isStringLiteral(n.name)) &&
      ts.isObjectLiteralExpression(n.initializer) &&
      has(n.initializer, 'method') &&
      has(n.initializer, 'path')
    ) {
      keys.push(n.name.text);
    }
    ts.forEachChild(n, visit);
  };
  visit(parse(rel, readRepo(rel)));
  return keys;
}

const where = (names: string[], used: Map<string, string[]>): string =>
  names.map((c) => `  ${c}  <- ${(used.get(c) ?? ['?']).slice(0, 3).join(', ')}`).join('\n');

// ── tests ───────────────────────────────────────────────────────────────────────────────────

describe('IPC contract gate', () => {
  it('T1: every command the renderer invokes is handled by the main process, or is a known gap', () => {
    const used = scanRendererInvokes();
    const handled = new Set([...Object.keys(COMMAND_ROUTES), ...mainProcessSpecialCommands()]);
    const fresh = [...used.keys()]
      .filter((c) => !handled.has(c) && !knownUnregistered.has(c))
      .sort();
    expect(
      fresh,
      'The renderer invokes commands the main process cannot dispatch ' +
        `(UnknownIpcCommandError at runtime):\n${where(fresh, used)}\n` +
        'Register them in electron/commands.ts or electron/commandRoutes/*.',
    ).toEqual([]);
  });

  it('T1: ipc-known-gaps.json holds no entry that is no longer a gap', () => {
    const used = scanRendererInvokes();
    const handled = new Set([...Object.keys(COMMAND_ROUTES), ...mainProcessSpecialCommands()]);
    const stale = [...knownUnregistered].filter((c) => handled.has(c) || !used.has(c)).sort();
    expect(
      stale,
      'Fixed (or no longer used) — delete from electron/ipc-known-gaps.json ' +
        `(frontendUnregistered):\n  ${stale.join('\n  ')}`,
    ).toEqual([]);
  });

  it('T1: main.ts special-cases the streaming commands the contract relies on', () => {
    // Guards the parser above: if it silently found nothing, every special command would be
    // reported as a new gap with a misleading message.
    expect(mainProcessSpecialCommands()).toEqual(
      expect.arrayContaining(['wiki_chat_stream', 'wiki_chat_cancel', 'wiki_ingest_stream']),
    );
  });

  it('T1: electron/ipc-manifest.json matches COMMAND_ROUTES', () => {
    const committed = JSON.parse(readRepo('electron/ipc-manifest.json')) as {
      commands: IpcManifest;
    };
    expect(
      buildIpcManifest(COMMAND_ROUTES),
      'electron/ipc-manifest.json is stale — run `npm run ipc:manifest` and commit it.',
    ).toEqual(committed.commands);
  });

  it('T1: every route targets the /api/v1 backend', () => {
    const offenders = Object.entries(buildIpcManifest(COMMAND_ROUTES))
      .filter(([, e]) => !e.path.startsWith('/api/v1/'))
      .map(([cmd, e]) => `${cmd} -> ${e.path}`);
    expect(offenders).toEqual([]);
  });

  it('T3: command keys are unique across commands.ts and electron/commandRoutes/*', () => {
    const dir = 'electron/commandRoutes';
    const files = [
      'electron/commands.ts',
      ...(existsSync(join(REPO_ROOT, dir)) ? listSources(dir) : []),
    ];
    const keys = files.flatMap(routeEntryKeys);
    const duplicates = [...new Set(keys.filter((k, i) => keys.indexOf(k) !== i))].sort();
    expect(
      duplicates,
      'Defined more than once — a later spread silently overrides an earlier entry.',
    ).toEqual([]);
    // Same count both ways: a key declared in a domain file that was never spread in (or the
    // reverse) means the table the main process sees differs from the source files.
    expect(keys.length).toBe(Object.keys(COMMAND_ROUTES).length);
  });

  it('buildIpcManifest turns arg probes into placeholders and drops the query string', () => {
    const routes: Record<string, CommandRoute> = {
      one: {
        method: 'GET',
        path: (a) =>
          `/api/v1/r/${encodeURIComponent(String(a.run_id ?? a.runId))}/s?limit=${a.limit}`,
      },
      two: { method: 'POST', path: () => '/api/v1/fixed' },
    };
    expect(buildIpcManifest(routes)).toEqual({
      one: { method: 'GET', path: '/api/v1/r/{run_id}/s' },
      two: { method: 'POST', path: '/api/v1/fixed' },
    });
  });
});
