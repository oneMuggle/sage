# Office staging dir orphan sweep — design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to implement this design.

**Date:** 2026-07-24
**Status:** design (post-brainstorming, pre-plan)
**Branch:** `fix/office-phase1-hardening` (continuation; will land on a new `fix/office-staging-sweep` branch)

## Problem

`electron/officeIpc.ts` creates a per-import staging directory at
`<workspace>/office/<docType>/<token>/` (where `<token>` is a UUID v4).
The directory is supposed to be deleted by `discardOfficeImport` if
parsing fails, and **kept** by `completeOfficeImport` if parsing
succeeds — the kept directory becomes the managed document.

Two failure modes leave the staging directory orphaned:

1. **App crash between stage and complete/discard.** The
   `pendingImports` Map lives in process memory; on restart the Map is
   empty, but the staged file on disk remains. The user sees no
   orphan, but disk usage grows over repeated crashes.
2. **Renderer never calls complete/discard.** A bug or renderer crash
   after pick-and-import but before the read returns leaves the
   staging file on disk indefinitely.

There is no current mechanism to clean these up. This design adds a
**startup-orphan sweep** scoped to a hidden `.pending/` namespace
that cannot collide with managed documents.

## Design

### Layout change: staging dir moves under `.pending/`

| | Path |
|---|---|
| **Before** | `<workspace>/office/<docType>/<token>/` |
| **After** | `<workspace>/office/.pending/<docType>/<token>/` |
| **Managed dir (unchanged)** | `<workspace>/office/<docType>/<id>/` |

`stageImportedFile` constructs the staging dir via a new
`pendingStagingDirectory(workspace, docType)` helper in
`electron/officePaths.ts` (parallel to the existing
`buildManagedPath`). The `PendingImport.stagingDir` field follows
automatically — it is captured at pick time from
`path.dirname(imported.managedPath)`, so discarding the captured
directory still works without code changes.

### Why `.pending/`?

Naming-space isolation guarantees the sweep can never delete a managed
document, even with no database coordination:

- The sweep enumerates `<workspace>/office/.pending/<docType>/<token>/`.
- A managed document lives at `<workspace>/office/<docType>/<id>/`,
  **outside** `.pending/`. The sweep's `rm -rf` only operates on
  paths inside `.pending/`, so a malformed `id` (or any other surprise)
  cannot be reached.

### Sweep function

```ts
async function sweepOrphanStaging(
  workspacePath: string,
): Promise<{ swept: number }> {
  const pendingRoot = path.join(workspacePath, 'office', '.pending');
  if (!existsSync(pendingRoot)) return { swept: 0 };

  let swept = 0;
  for (const docType of await readdir(pendingRoot)) {
    const typeDir = path.join(pendingRoot, docType);
    try {
      if (!statSync(typeDir).isDirectory()) continue;
    } catch {
      continue; // raced with another process — skip
    }
    for (const tokenDir of await readdir(typeDir)) {
      try {
        await rm(path.join(typeDir, tokenDir), { recursive: true, force: true });
        swept += 1;
      } catch (err) {
        // One orphan failing to delete must not block the rest of the
        // sweep; log and continue. The next lazy sweep will retry.
        logger.warn('office:staging-sweep: failed to remove orphan', {
          path: path.join(typeDir, tokenDir),
          err: String(err),
        });
      }
    }
  }
  return { swept };
}
```

### Trigger: lazy, on workspace selection

The sweep fires when `useOfficeDocuments(workspacePath)` detects a new
workspace (the existing `useEffect` that already calls `refresh`).
The two operations run in parallel:

```ts
useEffect(() => {
  void Promise.allSettled([
    refresh(),
    window.electronAPI?.office.sweepOrphanStaging(workspacePath),
  ]);
}, [refresh, workspacePath]);
```

Rationale for lazy (over app startup):

- **No workspace registry needed.** The renderer already knows the
  current `workspacePath`; startup-time sweep would need a
  `SELECT DISTINCT workspace_path FROM office_documents` round trip
  plus a new startup-callback slot in `electron/main.ts` after
  `waitForBackend()`.
- **No startup latency cost.** `sweepOrphanStaging` runs in the
  background while the user is still interacting with the workspace
  modal; the user does not perceive it.
- **Self-healing.** Any workspace the user visits gets swept
  eventually; there is no "first-workspace-after-cold-start" failure
  case to handle separately.

The sweep is **best-effort**: a failure is logged but does not block
the import flow. `Promise.allSettled` (over `Promise.all`) is used so
that a sweep error cannot prevent `refresh()` from completing.

### IPC surface

New channel `office:sweep-orphan-staging`:

```ts
// electron/officeIpc.ts (registerOfficeIpc)
register('office:sweep-orphan-staging',
  (async (_event: unknown, opts: { workspacePath: string }):
     Promise<{ swept: number }> => {
    if (!opts.workspacePath) throw new Error('workspacePath is required');
    return sweepOrphanStaging(opts.workspacePath);
  }) as (...args: unknown[]) => unknown,
);
```

`electron/preload.ts` exposes `sweepOrphanStaging(workspacePath: string):
Promise<{ swept: number }>`. `src/shared/types/electron-api.d.ts`
adds the typed bridge surface.

### Component changes

| File | Change |
|---|---|
| `electron/officePaths.ts` | New `pendingStagingDirectory(workspace, docType) → string` |
| `electron/officeIpc.ts` | `stageImportedFile` uses the new helper; new `sweepOrphanStaging` exported + IPC channel `office:sweep-orphan-staging` |
| `electron/preload.ts` | Expose `sweepOrphanStaging` on `window.electronAPI.office` |
| `src/shared/types/electron-api.d.ts` | Type the new bridge method |
| `src/features/office/useOfficeDocuments.ts` | Add sweep to the existing `useEffect([refresh, workspacePath])` via `Promise.allSettled` |

### Error handling

- `workspacePath` does not exist → `sweepOrphanStaging` throws
  `Error('workspacePath is required')` (matches existing
  `stageImportedFile` contract).
- `.pending/` does not exist → returns `{ swept: 0 }` (idempotent
  re-entry; first import after this PR will create the dir on demand).
- `readdir`/`statSync` on `.pending/` fails (e.g. permission, race) →
  skip that docType, continue.
- `rm` of a single orphan fails → log + continue (next sweep retries).
- IPC handler throws → renderer's `Promise.allSettled` catches it,
  `refresh()` proceeds unaffected.

### Testing

Unit (`electron/__tests__/officeIpc.test.ts`):

| Case | Expectation |
|---|---|
| Empty `.pending/` | returns `{ swept: 0 }`, does not throw |
| Missing `.pending/` | returns `{ swept: 0 }`, does not throw |
| 1 ppt orphan | returns `{ swept: 1 }`, dir is gone |
| 3 mixed (ppt/word/excel) orphans | returns `{ swept: 3 }`, all dirs gone |
| Managed dir `<workspace>/office/ppt/<id>/foo.pptx` exists alongside `.pending/ppt/<token>/bar.pptx` | only `.pending/ppt/<token>/` is removed; managed dir untouched |
| `rm` fails for one orphan (mock) | sweep logs warn, other orphans still removed, `{ swept: n-1 }` |

Integration (`src/features/office/__tests__/useOfficeDocuments.test.ts`):

| Case | Expectation |
|---|---|
| `workspacePath` changes from `null` to `'/tmp/ws'` | `sweepOrphanStaging` is called once with the new path |
| `sweepOrphanStaging` rejects | `refresh` still resolves, hook does not throw |

### Performance + safety

- Sweep is O(n) over `.pending/<docType>/<token>/`. Orphan count per
  workspace is bounded by the number of in-flight imports at crash
  time (typically 0-3 in practice).
- Sweep NEVER touches paths outside `.pending/`. The
  `path.join` of `pendingRoot` is computed once and reused; every
  subsequent `path.join(typeDir, tokenDir)` is rooted under it.
- Sweep is lazy-triggered, so it does not add to app startup latency.
- Sweep is best-effort; one failure does not block other orphans or
  the import flow.

## Out of scope

- **No active "purge now" UI.** The sweep is implicit on workspace
  selection. A future settings-page button is possible but not part
  of this PR.
- **No metadata-file sentinel.** The `.pending/` namespace isolation
  removes the need for `.staging-token` files.
- **No startup-time cross-workspace sweep.** Lazy trigger is
  sufficient; a startup scan would require a workspace registry and
  adds complexity for marginal benefit.
- **No change to `completeOfficeImport` semantics.** Completed
  imports keep the staging dir (now under `.pending/`) — but only
  transiently; the renderer immediately triggers a workspace
  document refresh, which does not write into `.pending/`. The
  staging dir's contents become the managed dir when the document is
  refreshed? No — actually, on success, the renderer reads from the
  managed file and the staging dir is retained (same content). The
  next sweep removes it. **This needs re-checking against the actual
  completeOfficeImport behavior.** If the staging dir is meant to
  become the managed dir (renamed, not deleted), the sweep must NOT
  delete it. See **Open question** below.

## Open question

Does `completeOfficeImport` rename the staging dir to the managed
dir, or does it leave it in place?

- If it renames (`pending/token/` → `office/<docType>/<id>/`): the
  sweep is harmless (sweep finds nothing under `.pending/`).
- If it leaves the dir in place at `.pending/<docType>/<token>/` and
  the managed dir is a separate copy: the sweep would delete a
  file the renderer just imported. **This would be a bug.**

The plan step before implementation must read
`electron/officeIpc.ts` `completeOfficeImport` (around line 257) and
verify the answer. If it leaves the dir in place, the fix is either
(a) move the dir on complete, or (b) exclude the just-completed token
from the sweep.

## Why

Closes the 6th Minor follow-up from the M0 milestone (`staging dir
缺 startup-time orphan sweep`, deferred from `105cae1`). Required for
M1-M2 chat-read: by the time users are reading managed documents
through the chat flow, repeated crash-restart cycles must not leave
visible disk bloat under the workspace.

**How to apply:** Implementation plan goes on a new
`fix/office-staging-sweep` branch. Open question above must be
answered before any sweep code is written; the plan should include a
verification step that reads `completeOfficeImport` and updates the
design accordingly.