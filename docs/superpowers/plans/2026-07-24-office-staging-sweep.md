# Office staging-dir orphan sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lazy, db-coordinated sweep that deletes orphan Office staging dirs under `<workspace>/office/<docType>/<dir>/` whose `<dir>` is no longer present in `office_documents.id` (i.e. crashed imports that never reached `completeOfficeImport` or `discardOfficeImport`).

**Architecture:** The Electron main process exposes a new IPC channel `office:sweep-orphan-staging` that takes the current `workspacePath` and a list of `knownDocIds` (which the renderer has just fetched via `office_list_documents`). The renderer-side `useOfficeDocuments` hook replaces its single `refresh()` call with a sequenced `listDocuments → setDocuments → sweepOrphanStaging` flow so the sweep always has the freshest known id set. The sweep itself is a single `readdir` + `rm -rf` loop, scoped strictly to the `<workspace>/office/` subtree.

**Tech Stack:** Electron 21.4.4, TypeScript, vitest, Node `fs/promises`, IPC `ipcMain.handle`.

**Spec:** `docs/superpowers/specs/2026-07-24-office-staging-sweep-design.md` (post-Open-question, db-coordinated variant)

## Global Constraints

- One orphan = `<workspace>/office/<docType>/<dir>/<basename>` whose `<dir>` is NOT in `office_documents.id` for the matching `(workspace_path, doc_type)`. There is no separate staging namespace (see spec §"Key invariant").
- Sweep is **always** gated on a non-empty `knownDocIds` from a fresh `office_list_documents` call. No sweep without db coordination.
- Sweep NEVER touches paths outside `<workspacePath>/office/`. The `path.join` of `officeRoot` is computed once and reused.
- One failing `rm` does NOT abort the sweep — log `logger.warn` and continue. Next sweep will retry.
- IPC handler type: `Promise<{ swept: number }>`. Never throws on the happy path; throws `Error('workspacePath is required')` only when caller omits the field.
- Existing `useOfficeDocuments` behavior (refresh, error, loading state, importAndRead, saveAs, open, showInFolder) is preserved. Only the `useEffect([workspacePath])` body changes.
- Each task = one commit. Conventional Commits.

## File Map

| File | Role | Change |
|---|---|---|
| `electron/officeIpc.ts` | Electron main IPC gateway | Add `sweepOrphanStaging(workspacePath, knownDocIds)` exported; add `office:sweep-orphan-staging` IPC channel inside `registerOfficeIpc` |
| `electron/preload.ts` | Bridge exposure | Expose `sweepOrphanStaging({ workspacePath, knownDocIds })` on `window.electronAPI.office` |
| `src/shared/types/electron-api.d.ts` | Renderer type surface | Add `sweepOrphanStaging(opts)` typed method |
| `src/features/office/useOfficeDocuments.ts` | Hook implementation | Replace single `refresh()` in `useEffect` with `listDocuments → setDocuments → sweepOrphanStaging` sequence; add `cancelled` guard |
| `electron/__tests__/officeIpc.test.ts` | Electron unit tests | Add 6 cases from spec §Testing |
| `src/features/office/__tests__/useOfficeDocuments.test.ts` | Hook integration tests | Add 4 cases from spec §Testing |

---

### Task 0: Create feature branch

**Files:** none — git operation only.

**Interfaces:** N/A.

- [ ] **Step 1: Confirm current branch**

Run: `cd /home/fz/project/sage && git branch --show-current`
Expected: `fix/office-phase1-hardening` (the current branch with M0 + F1-F4 already committed).

- [ ] **Step 2: Create and switch to the new branch**

Run:
```bash
cd /home/fz/project/sage && \
  git switch -c fix/office-staging-sweep
```

Expected: `Switched to a new branch 'fix/office-staging-sweep'`. Branch is created from the current HEAD (which has the spec + plan + F1-F4 hygiene commits).

- [ ] **Step 3: Verify the branch is clean**

Run: `cd /home/fz/project/sage && git status`
Expected: `On branch fix/office-staging-sweep`, `nothing to commit, working tree clean`.

(No commit for this task — the branch creation is not a code change.)

---

### Task 1: Add `sweepOrphanStaging` and IPC channel (electron/officeIpc.ts)

**Files:**
- Modify: `electron/officeIpc.ts` (add `sweepOrphanStaging` exported function and `office:sweep-orphan-staging` handler inside `registerOfficeIpc`)
- Modify: `electron/__tests__/officeIpc.test.ts` (add 6 unit tests)

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the foundation)
- Produces:
  ```ts
  // electron/officeIpc.ts
  export async function sweepOrphanStaging(
    workspacePath: string,
    knownDocIds: ReadonlySet<string>,
  ): Promise<{ swept: number }>
  ```
- IPC channel `office:sweep-orphan-staging` accepts `{ workspacePath: string; knownDocIds: string[] }` and returns `{ swept: number }`.

- [ ] **Step 1: Write the failing tests**

Open `electron/__tests__/officeIpc.test.ts` and add the following 6 tests inside a new `describe('sweepOrphanStaging', ...)` block (placement: at the bottom of the file, after the existing tests):

```ts
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

import { sweepOrphanStaging, registerOfficeIpc, __resetPendingImportsForTests } from '../officeIpc';

function freshWorkspace(): string {
  const ws = join(tmpdir(), `sage-sweep-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  mkdirSync(ws, { recursive: true });
  return ws;
}

describe('sweepOrphanStaging', () => {
  beforeEach(() => {
    __resetPendingImportsForTests();
  });

  it('returns swept:0 when workspace has no office/ directory', async () => {
    const ws = freshWorkspace();
    try {
      const result = await sweepOrphanStaging(ws, new Set());
      expect(result).toEqual({ swept: 0 });
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  });

  it('returns swept:0 when office/ exists but has no docType subdirs', async () => {
    const ws = freshWorkspace();
    mkdirSync(join(ws, 'office'));
    try {
      const result = await sweepOrphanStaging(ws, new Set());
      expect(result).toEqual({ swept: 0 });
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  });

  it('removes a single orphan ppt dir when its name is not in knownDocIds', async () => {
    const ws = freshWorkspace();
    const orphan = join(ws, 'office', 'ppt', 'aaaa-bbbb-cccc');
    mkdirSync(join(orphan, 'inner'), { recursive: true });
    writeFileSync(join(orphan, 'inner', 'deck.pptx'), 'fake');
    try {
      const result = await sweepOrphanStaging(ws, new Set());
      expect(result).toEqual({ swept: 1 });
      expect(existsSync(orphan)).toBe(false);
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  });

  it('preserves a managed dir whose name is in knownDocIds', async () => {
    const ws = freshWorkspace();
    const managedDir = join(ws, 'office', 'ppt', 'managed-uuid-1');
    mkdirSync(join(managedDir, 'inner'), { recursive: true });
    writeFileSync(join(managedDir, 'inner', 'deck.pptx'), 'fake');
    try {
      const result = await sweepOrphanStaging(ws, new Set(['managed-uuid-1']));
      expect(result).toEqual({ swept: 0 });
      expect(existsSync(managedDir)).toBe(true);
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  });

  it('removes only orphans when 3 dirs exist (2 orphan + 1 managed)', async () => {
    const ws = freshWorkspace();
    const orphan1 = join(ws, 'office', 'ppt', 'orphan-1');
    const orphan2 = join(ws, 'office', 'word', 'orphan-2');
    const managed = join(ws, 'office', 'ppt', 'managed-3');
    for (const d of [orphan1, orphan2, managed]) {
      mkdirSync(join(d, 'inner'), { recursive: true });
      writeFileSync(join(d, 'inner', 'doc'), 'fake');
    }
    try {
      const result = await sweepOrphanStaging(ws, new Set(['managed-3']));
      expect(result).toEqual({ swept: 2 });
      expect(existsSync(orphan1)).toBe(false);
      expect(existsSync(orphan2)).toBe(false);
      expect(existsSync(managed)).toBe(true);
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  });

  it('does not abort the sweep when one rm fails (best-effort)', async () => {
    const ws = freshWorkspace();
    const okOrphan = join(ws, 'office', 'ppt', 'ok-orphan');
    mkdirSync(join(okOrphan, 'inner'), { recursive: true });
    writeFileSync(join(okOrphan, 'inner', 'deck.pptx'), 'fake');

    const badOrphan = join(ws, 'office', 'word', 'bad-orphan');
    mkdirSync(badOrphan, { recursive: true });
    const locked = join(badOrphan, 'locked');
    mkdirSync(locked);
    writeFileSync(join(locked, 'x'), 'data');
    try {
      // Make badOrphan un-removable for the current user on POSIX.
      // chmod may fail on some CI setups (Windows, root); the test
      // still exercises the try/catch path either way.
      try {
        const { chmodSync } = await import('fs');
        chmodSync(badOrphan, 0o000);
      } catch {
        // best-effort chmod
      }

      const result = await sweepOrphanStaging(ws, new Set());
      expect(result.swept).toBeGreaterThanOrEqual(1);
      expect(existsSync(okOrphan)).toBe(false);
    } finally {
      try { (await import('fs')).chmodSync(badOrphan, 0o755); } catch {}
      rmSync(ws, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run the new tests to verify RED**

Run: `cd /home/fz/project/sage && npm run test:run -- electron/__tests__/officeIpc.test.ts`
Expected: FAIL — `sweepOrphanStaging` is not exported from `officeIpc.ts`.

- [ ] **Step 3: Implement `sweepOrphanStaging` and the IPC channel**

Open `electron/officeIpc.ts`. Confirm the logger import path with:

```bash
grep -n "^import.*logger\|from './logger'\|from \"./logger\"" /home/fz/project/sage/electron/officeIpc.ts /home/fz/project/sage/electron/main.ts | head -5
```

If `electron/logger` (or similar) is the project's logger module, add this import near the existing imports:

```ts
import { logger } from './logger';
```

(If no logger module exists, use `console.warn` as a fallback and replace with the real logger in a follow-up; the spec assumes `logger.warn`.)

Add the following imports near the top of `officeIpc.ts` (alongside the existing `fs/promises` import — keep alphabetical):

```ts
import { existsSync, readdirSync, statSync } from 'fs';
import { readdir, rm } from 'fs/promises';
import { join } from 'path';
```

Insert the function immediately above the existing `registerOfficeIpc` function:

```ts
/**
 * Sweep orphan staging directories under <workspace>/office/.
 *
 * An "orphan" is a directory at <workspace>/office/<docType>/<dir>/
 * whose `<dir>` is NOT in `knownDocIds` (the set of document ids the
 * renderer just fetched from office_list_documents). Staging and
 * managed documents share the same directory layout — see
 * docs/superpowers/specs/2026-07-24-office-staging-sweep-design.md
 * §"Key invariant" for why db coordination is required.
 *
 * Best-effort: a single `rm` failure does NOT abort the sweep; the
 * rest of the orphans are still removed and the failure is logged.
 */
export async function sweepOrphanStaging(
  workspacePath: string,
  knownDocIds: ReadonlySet<string>,
): Promise<{ swept: number }> {
  if (!workspacePath) {
    throw new Error('workspacePath is required');
  }
  const officeRoot = join(workspacePath, 'office');
  if (!existsSync(officeRoot)) return { swept: 0 };

  let swept = 0;
  for (const docType of readdirSync(officeRoot)) {
    const typeDir = join(officeRoot, docType);
    try {
      if (!statSync(typeDir).isDirectory()) continue;
    } catch {
      continue; // raced with another process — skip
    }
    for (const dirName of await readdir(typeDir)) {
      if (knownDocIds.has(dirName)) continue; // managed — keep
      try {
        await rm(join(typeDir, dirName), { recursive: true, force: true });
        swept += 1;
      } catch (err) {
        logger.warn('office:staging-sweep: failed to remove orphan', {
          path: join(typeDir, dirName),
          err: String(err),
        });
      }
    }
  }
  return { swept };
}
```

Now register the IPC channel inside `registerOfficeIpc`. Add the following handler block immediately after the `office:discard-import` handler (which ends around line 286):

```ts
  // ── office:sweep-orphan-staging ──────────────────────────────────────
  // Lazy, db-coordinated cleanup. The renderer calls
  // office_list_documents first, then passes the resulting id list
  // here. The handler walks <workspace>/office/<docType>/<dir> and
  // deletes any <dir> not in knownDocIds. See
  // docs/superpowers/specs/2026-07-24-office-staging-sweep-design.md
  // for the full design.
  register(
    'office:sweep-orphan-staging',
    (async (
      _event: unknown,
      opts: { workspacePath: string; knownDocIds: string[] },
    ): Promise<{ swept: number }> => {
      return sweepOrphanStaging(opts.workspacePath, new Set(opts.knownDocIds));
    }) as (...args: unknown[]) => unknown,
  );
```

- [ ] **Step 4: Run the new tests to verify GREEN**

Run: `cd /home/fz/project/sage && npm run test:run -- electron/__tests__/officeIpc.test.ts`
Expected: PASS for all 6 new tests + the 14 existing `officeIpc` tests (20 total in this file).

- [ ] **Step 5: Run typecheck to verify no regressions**

Run: `cd /home/fz/project/sage && npm run typecheck:electron`
Expected: PASS — no new type errors.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && \
  git add electron/officeIpc.ts electron/__tests__/officeIpc.test.ts && \
  git commit -m "feat(office): sweep orphan staging dirs on workspace entry

Implements the db-coordinated sweep from
docs/superpowers/specs/2026-07-24-office-staging-sweep-design.md
(Task 1 of the plan):

- new exported sweepOrphanStaging(workspacePath, knownDocIds) walks
  <workspace>/office/<docType>/<dir> and removes any <dir> not in
  the known id set
- new IPC channel office:sweep-orphan-staging wires the renderer-
  computed knownDocIds through ipcMain
- 6 new unit tests cover: empty/missing office/, single orphan,
  managed-dir preservation, mixed 3 dirs (2 orphan + 1 managed),
  per-rm best-effort isolation

Staging and managed dirs share the same path layout (see spec
§'Key invariant': office_routes.py uses file_path.parent.name as
document_id), so the db lookup is REQUIRED — there is no separate
staging namespace to sweep independently."
```

---

### Task 2: Expose `sweepOrphanStaging` on the renderer bridge

**Files:**
- Modify: `electron/preload.ts` (add `sweepOrphanStaging` to the `office` surface)
- Modify: `src/shared/types/electron-api.d.ts` (add the type signature)

**Interfaces:**
- Consumes: `sweepOrphanStaging` from Task 1 (just IPC channel name + signature)
- Produces: `window.electronAPI.office.sweepOrphanStaging({ workspacePath, knownDocIds }) → Promise<{ swept: number }>`

- [ ] **Step 1: Read the existing preload `office` block to mirror its shape**

Run: `grep -n "office" /home/fz/project/sage/electron/preload.ts | head -30`
Expected: a section like `office: { ... }` with existing methods such as `pickAndImportOfficeFile`, `completeOfficeImport`, `discardOfficeImport`, `saveOfficeDocumentAs`, `openOfficeDocument`, `showOfficeDocumentInFolder`.

- [ ] **Step 2: Add `sweepOrphanStaging` to `electron/preload.ts`**

Open `electron/preload.ts` and add the following method inside the `office` object, immediately after `discardOfficeImport`:

```ts
    sweepOrphanStaging: (opts: { workspacePath: string; knownDocIds: string[] }): Promise<{ swept: number }> =>
      ipcRenderer.invoke('office:sweep-orphan-staging', opts),
```

(Match the surrounding style — same indentation, same arrow-function vs `function` choice as the adjacent entries. If the file uses `function` declarations, use `function sweepOrphanStaging(opts) { return ipcRenderer.invoke(...) }` instead.)

- [ ] **Step 3: Add the type signature in `src/shared/types/electron-api.d.ts`**

Open `src/shared/types/electron-api.d.ts`, locate the `OfficeApi` (or equivalent) interface that holds the existing `pickAndImportOfficeFile`, `completeOfficeImport`, etc. methods. Add inside the same interface:

```ts
  sweepOrphanStaging: (opts: {
    workspacePath: string;
    knownDocIds: string[];
  }) => Promise<{ swept: number }>;
```

- [ ] **Step 4: Run typecheck to verify the bridge types align**

Run: `cd /home/fz/project/sage && npm run typecheck && npm run typecheck:electron`
Expected: PASS for both — preload usage and renderer consumer types agree.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && \
  git add electron/preload.ts src/shared/types/electron-api.d.ts && \
  git commit -m "feat(office): expose sweepOrphanStaging on renderer bridge

Wires the new IPC channel from Task 1 through preload + the typed
electron-api surface so useOfficeDocuments can call it."
```

---

### Task 3: Sequence listDocuments → setDocuments → sweep in `useOfficeDocuments`

**Files:**
- Modify: `src/features/office/useOfficeDocuments.ts` (replace the single `refresh()` call in the workspace-change `useEffect` with the sequenced list-then-sweep flow)
- Modify: `src/features/office/__tests__/useOfficeDocuments.test.ts` (add 4 integration tests from the spec)

**Interfaces:**
- Consumes:
  - `officeApi.listDocuments(workspacePath): Promise<{ documents: OfficeDocumentSummary[] }>` (existing)
  - `window.electronAPI.office.sweepOrphanStaging({ workspacePath, knownDocIds })` (Task 2)
- Produces: `useOfficeDocuments(workspacePath)` behavior change — the workspace-change `useEffect` now:
  1. Fetches `listDocuments` first
  2. `setDocuments(...)` with the result
  3. Calls `sweepOrphanStaging` with the document ids
  4. Surfaces errors via `setError`
  5. Uses a `cancelled` flag in cleanup so a stale workspace change can't `setDocuments` after unmount or after a later change

- [ ] **Step 1: Write the failing integration tests**

Open `src/features/office/__tests__/useOfficeDocuments.test.ts` (create the file if it does not exist — verify with `ls src/features/office/__tests__/useOfficeDocuments.test.ts`). Add the following tests at the end of the existing file:

```ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  officeApiListDocuments: vi.fn(),
  electronSweep: vi.fn(),
}));

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listDocuments: mocks.officeApiListDocuments,
  },
}));

import { useOfficeDocuments } from '../useOfficeDocuments';

describe('useOfficeDocuments — workspace entry sweep', () => {
  beforeEach(() => {
    mocks.officeApiListDocuments.mockReset();
    mocks.electronSweep.mockReset();
    (window as unknown as { electronAPI?: unknown }).electronAPI = {
      office: {
        sweepOrphanStaging: mocks.electronSweep,
      },
    };
  });

  it('calls listDocuments then sweepOrphanStaging with the same workspace and known ids', async () => {
    mocks.officeApiListDocuments.mockResolvedValue({
      documents: [
        { id: 'doc-a', workspace_path: '/tmp/ws', doc_type: 'ppt', original_filename: 'a.pptx', generated_filename: 'a.pptx', status: 'parsed', created_at: 0, updated_at: 0, metadata: { file_size_bytes: 1 } },
        { id: 'doc-b', workspace_path: '/tmp/ws', doc_type: 'word', original_filename: 'b.docx', generated_filename: 'b.docx', status: 'parsed', created_at: 0, updated_at: 0, metadata: { file_size_bytes: 1 } },
      ],
    });
    mocks.electronSweep.mockResolvedValue({ swept: 0 });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.documents).toHaveLength(2);
    });
    expect(mocks.officeApiListDocuments).toHaveBeenCalledWith('/tmp/ws');
    expect(mocks.electronSweep).toHaveBeenCalledWith({
      workspacePath: '/tmp/ws',
      knownDocIds: ['doc-a', 'doc-b'],
    });
  });

  it('skips sweep when listDocuments rejects (no known ids to gate on)', async () => {
    mocks.officeApiListDocuments.mockRejectedValue(new Error('backend down'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.error).toMatch(/backend down/);
    });
    expect(mocks.electronSweep).not.toHaveBeenCalled();
  });

  it('surfaces sweep failure without losing the documents list', async () => {
    mocks.officeApiListDocuments.mockResolvedValue({
      documents: [
        { id: 'doc-x', workspace_path: '/tmp/ws', doc_type: 'ppt', original_filename: 'x.pptx', generated_filename: 'x.pptx', status: 'parsed', created_at: 0, updated_at: 0, metadata: { file_size_bytes: 1 } },
      ],
    });
    mocks.electronSweep.mockRejectedValue(new Error('rm failed'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });
    await waitFor(() => {
      expect(result.current.error).toMatch(/rm failed/);
    });
  });

  it('does not setDocuments on an unmounted hook when workspace changes mid-flight', async () => {
    let resolveList: ((v: { documents: unknown[] }) => void) | null = null;
    mocks.officeApiListDocuments.mockImplementation(
      () =>
        new Promise((res) => {
          resolveList = res;
        }),
    );
    mocks.electronSweep.mockResolvedValue({ swept: 0 });

    const { result, rerender } = renderHook(
      ({ ws }) => useOfficeDocuments(ws),
      { initialProps: { ws: '/tmp/first' } },
    );
    rerender({ ws: '/tmp/second' });
    resolveList!({ documents: [] });
    await waitFor(() => {
      expect(result.current.documents).toEqual([]);
    });
    expect(mocks.electronSweep).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `cd /home/fz/project/sage && npm run test:run -- src/features/office/__tests__/useOfficeDocuments.test.ts`
Expected: FAIL — the existing `useOfficeDocuments` calls `refresh()` (which calls `listDocuments` AND `setDocuments` but does NOT call `sweepOrphanStaging` and does NOT have the `cancelled` guard), so the first two tests fail on `expect(mocks.electronSweep).toHaveBeenCalledWith(...)` and the fourth fails on the cancellation assertion.

- [ ] **Step 3: Rewrite the workspace-change `useEffect` in `useOfficeDocuments.ts`**

Open `src/features/office/useOfficeDocuments.ts`. Before changing anything, verify whether the existing `refresh` callback is referenced elsewhere:

Run: `grep -rn "refresh" /home/fz/project/sage/src/features/office/`
Expected: should show only the `refresh` definition inside `useOfficeDocuments` (no external callers). If something else calls it, keep `refresh` and only swap the `useEffect` body.

Replace the existing `useEffect` (currently around lines 106-109, the one that calls `void refresh()` on the `refresh` change) with:

```ts
  // Workspace entry: list first, then sweep with the known id set.
  // Cancellation guard prevents a stale resolution from a prior
  // workspace from clobbering the new workspace's documents.
  useEffect(() => {
    if (!workspacePath) {
      setDocuments([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const { documents } = await officeApi.listDocuments(workspacePath);
        if (cancelled) return;
        setDocuments(documents);
        // Best-effort: a sweep failure surfaces via setError but does
        // not undo the documents we just listed.
        try {
          await window.electronAPI?.office.sweepOrphanStaging({
            workspacePath,
            knownDocIds: documents.map((d) => d.id),
          });
        } catch (sweepErr) {
          if (cancelled) return;
          setError(sweepErr instanceof Error ? sweepErr.message : String(sweepErr));
        }
      } catch (listErr) {
        if (cancelled) return;
        setError(listErr instanceof Error ? listErr.message : String(listErr));
        setDocuments([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);
```

If the existing `refresh` callback is unused elsewhere, delete the `const refresh = useCallback(...)` block to avoid dead code. Verify with `grep -n "refresh" src/features/office/useOfficeDocuments.ts` after the edit.

- [ ] **Step 4: Run the integration tests to verify GREEN**

Run: `cd /home/fz/project/sage && npm run test:run -- src/features/office/__tests__/useOfficeDocuments.test.ts`
Expected: PASS for all 4 new tests + the existing `useOfficeDocuments` tests (4 from M0 Task 6 + 4 new = 8 total in this file).

- [ ] **Step 5: Run typecheck**

Run: `cd /home/fz/project/sage && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage && \
  git add src/features/office/useOfficeDocuments.ts \
          src/features/office/__tests__/useOfficeDocuments.test.ts && \
  git commit -m "feat(office): sweep orphan staging on workspace entry

Replaces the single refresh() in useOfficeDocuments's workspace-
change effect with the sequenced listDocuments → setDocuments →
sweepOrphanStaging flow required by the spec:

- listDocuments first so the renderer has a known id set
- sweepOrphanStaging then deletes <workspace>/office/<docType>/<dir>
  for any <dir> not in the known set
- cancellation flag (cancelled) prevents a stale workspace's
  resolution from clobbering the new workspace's documents
- best-effort error handling: a sweep failure surfaces via setError
  but does not undo the documents we just listed; a list failure
  skips the sweep entirely (no known ids to gate on)

This closes F5 (deferred from 105cae1) and prepares the workspace
state for M1-M2 chat-read: any crash-restart orphan is cleaned
up the next time the user picks the workspace."
```

---

### Task 4: Verification gate

**Files:** none modified — pure verification.

- [ ] **Step 1: Run electron unit tests**

Run: `cd /home/fz/project/sage && npm run test:run -- electron/__tests__/officeIpc.test.ts`
Expected: PASS — 20 tests (14 existing + 6 new from Task 1).

- [ ] **Step 2: Run hook integration tests**

Run: `cd /home/fz/project/sage && npm run test:run -- src/features/office/__tests__/useOfficeDocuments.test.ts`
Expected: PASS — 8 tests (4 existing + 4 new from Task 3).

- [ ] **Step 3: Run typecheck (renderer + electron)**

Run: `cd /home/fz/project/sage && npm run typecheck && npm run typecheck:electron`
Expected: PASS for both.

- [ ] **Step 4: Run the full Office test + production build gates**

Run: `cd /home/fz/project/sage && npm run test:run -- src/features/office electron/__tests__/officePaths.test.ts electron/__tests__/officeIpc.test.ts`
Expected: PASS.

Run: `cd /home/fz/project/sage && npm run build`
Expected: PASS — `built in <N> seconds`.

- [ ] **Step 5: Manual smoke (optional)**

If a workspace is available with pre-existing orphan dirs, open that workspace in the app and confirm:
- The orphan dirs under `<workspace>/office/<docType>/<orphan-uuid>/` disappear.
- The list of managed documents in `/office` is unchanged.
- No errors in the Electron main process log.

If no orphan exists, this step is a no-op; the test suite already covers the behavior.

- [ ] **Step 6: Commit verification notes (if any)**

If the manual smoke surfaced anything actionable, commit the fix as a separate `fix(office):` commit. Otherwise, no commit for this task.

---

### Task 5: M1-M2 pre-flight memory update

**Files:**
- Modify: `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-office-m0-minor-hygiene-merged.md` (mark F5 closed)
- Modify: `/home/fz/.claude/projects/-home-fz-project-sage/memory/MEMORY.md` (update the line that defers F5)

**Interfaces:** N/A (memory only).

- [ ] **Step 1: Edit `sage-office-m0-minor-hygiene-merged.md`**

Change the `## Deferred (1/5)` heading to `## Closed (5/5)` and add a row to the table:

```markdown
| F5: staging dir orphan sweep | New `sweepOrphanStaging(workspacePath, knownDocIds)` IPC + lazy `listDocuments → setDocuments → sweepOrphanStaging` flow in `useOfficeDocuments`. Spec at `docs/superpowers/specs/2026-07-24-office-staging-sweep-design.md` (post-Open-question, db-coordinated variant). |
```

Also append a short "Postscript (F5 closure, 2026-07-24)" subsection under `## Verification` summarizing the branch name + commit count.

- [ ] **Step 2: Edit `MEMORY.md`**

Find the line:
```
- [Sage: Office M0 Minor hygiene (2026-07-24)](sage-office-m0-minor-hygiene-merged.md) — fix/office-phase1-hardening @ 105cae1, 4/5 follow-ups closed, F5 deferred 到独立 PR (需 sweep 时机 + db 协调 + namespace 决策)
```

Update it to read:
```
- [Sage: Office M0 Minor hygiene + F5 sweep (2026-07-24)](sage-office-m0-minor-hygiene-merged.md) — fix/office-phase1-hardening + fix/office-staging-sweep, 5/5 follow-ups closed (F5 resolved as db-coordinated sweep per spec 2026-07-24)
```

- [ ] **Step 3: No commit (memory files live outside git)**

Memory files are read by the harness, not committed. Stop here.