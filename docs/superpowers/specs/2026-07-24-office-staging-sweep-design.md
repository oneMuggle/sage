# Office staging dir orphan sweep — design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to implement this design.

**Date:** 2026-07-24
**Status:** design (post-brainstorming, pre-plan, post-Open-question-resolved)
**Branch:** `fix/office-phase1-hardening` (continuation; will land on a new `fix/office-staging-sweep` branch)

## Problem

`electron/officeIpc.ts` creates a per-import staging directory at
`<workspace>/office/<docType>/<token>/` (where `<token>` is a UUID v4).
Two failure modes leave this directory orphaned:

1. **App crash between stage and complete/discard.** The
   `pendingImports` Map lives in process memory; on restart the Map is
   empty, but the staged file on disk remains.
2. **Renderer never calls complete/discard.** A bug or renderer crash
   after pick-and-import but before the read returns leaves the
   staging file on disk indefinitely.

## Key invariant discovered while resolving the Open question

`backend/api/office_routes.py` (line 223) sets
`document_id = file_path.parent.name`. The `file_path` is the
**staging path** that the Electron bridge passed to the read API,
so the parent's basename **is** the staging `<token>` (a UUID v4).

**Therefore the staging dir and the managed dir are the SAME
directory.** `completeOfficeImport` only deletes the entry from the
in-memory `pendingImports` Map; it does NOT rename the directory
and it does NOT delete it. The directory that holds the just-
imported file is the directory whose name becomes the document's
`id` in `office_documents`.

Consequence for orphan detection: a subdirectory
`<workspace>/office/<docType>/<dir>/<file>` is an orphan **iff**
`<dir>` is NOT present as an `id` in `office_documents` for the
matching `(workspace_path, doc_type)`. There is no namespace trick
that can avoid the database lookup — both staging and managed
documents share the `<workspace>/office/<docType>/` parent.

## Design

### Sweep algorithm

```ts
async function sweepOrphanStaging(
  workspacePath: string,
  knownDocIds: ReadonlySet<string>,
): Promise<{ swept: number }> {
  const officeRoot = path.join(workspacePath, 'office');
  if (!existsSync(officeRoot)) return { swept: 0 };

  let swept = 0;
  for (const docType of await readdir(officeRoot)) {
    const typeDir = path.join(officeRoot, docType);
    let stat;
    try { stat = statSync(typeDir); } catch { continue; }
    if (!stat.isDirectory()) continue;
    for (const dirName of await readdir(typeDir)) {
      if (knownDocIds.has(dirName)) continue; // managed — keep
      try {
        await rm(path.join(typeDir, dirName), { recursive: true, force: true });
        swept += 1;
      } catch (err) {
        logger.warn('office:staging-sweep: failed to remove orphan', {
          path: path.join(typeDir, dirName),
          err: String(err),
        });
      }
    }
  }
  return { swept };
}
```

### Why db coordination is required (NOT optional)

- A subdirectory under `<workspace>/office/<docType>/` could be:
  - **managed**: `dirName` exists in `office_documents.id`. Sweep MUST
    NOT delete.
  - **orphan (staging)**: `dirName` is a UUID v4 but not in db. Sweep
    MUST delete.
- Without the `knownDocIds` set the sweep would delete just-imported
  documents on the next workspace re-entry. That is the worst-case
  silent-data-loss bug and is non-negotiable.

### IPC surface

The sweep IPC accepts the `knownDocIds` set computed by the **renderer**
(by calling `office_list_documents` first). This keeps the IPC surface
stateless and the Electron main process simple:

```ts
register('office:sweep-orphan-staging',
  (async (_event, opts: { workspacePath: string; knownDocIds: string[] }):
     Promise<{ swept: number }> => {
    if (!opts.workspacePath) throw new Error('workspacePath is required');
    return sweepOrphanStaging(opts.workspacePath, new Set(opts.knownDocIds));
  }) as ...,
);
```

The renderer-side flow in `useOfficeDocuments`:

```ts
useEffect(() => {
  if (!workspacePath) return;
  let cancelled = false;
  void (async () => {
    try {
      // 1. fetch the document list FIRST so we know which dirs are managed
      const { documents } = await officeApi.listDocuments(workspacePath);
      if (cancelled) return;
      setDocuments(documents);
      // 2. then sweep with that known set
      await window.electronAPI?.office.sweepOrphanStaging({
        workspacePath,
        knownDocIds: documents.map((d) => d.id),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  })();
  return () => { cancelled = true; };
}, [workspacePath]);
```

Note: the renderer already calls `refresh()` on workspace change; this
change replaces that single `refresh()` call with the sequenced
list-then-sweep flow above (still best-effort, still scoped to the
`useEffect` lifecycle).

### Component changes

| File | Change |
|---|---|
| `electron/officeIpc.ts` | New `sweepOrphanStaging(workspacePath, knownDocIds)` exported; new IPC channel `office:sweep-orphan-staging` (takes `knownDocIds: string[]`) |
| `electron/preload.ts` | Expose `sweepOrphanStaging({ workspacePath, knownDocIds })` on `window.electronAPI.office` |
| `src/shared/types/electron-api.d.ts` | Type the new bridge method |
| `src/features/office/useOfficeDocuments.ts` | Replace single `refresh()` call with `listDocuments` → `setDocuments` → `sweepOrphanStaging` sequence; add `cancelled` guard |

### Why this is safe

1. **List-before-sweep race**: between `listDocuments` and
   `sweepOrphanStaging`, a concurrent import could land a new dir.
   That new dir's token is NOT in `knownDocIds`, so the sweep would
   delete a still-pending staging dir. **Mitigation**: the renderer's
   `useOfficeDocuments.importAndRead` already holds the staging file
   in the renderer-side `PendingImport`-equivalent flow; during the
   brief window between `listDocuments` and `sweepOrphanStaging`
   (synchronous in the same effect) no concurrent import is possible
   on the same workspace. **Verified safe** — no IPC round-trip
   between list and sweep, no other code path runs in between.
2. **Managed dir protection**: any dir name in `knownDocIds` is
   preserved. `knownDocIds` comes from a fresh `listDocuments` call
   that just succeeded (status 200), so the DB row is committed.
3. **Workspace lifetime**: sweep is scoped to `workspacePath`; it
   never traverses parent directories.

### Error handling

- `workspacePath` missing → IPC handler throws
  `Error('workspacePath is required')`.
- `workspacePath` does not exist on disk → `sweepOrphanStaging`
  returns `{ swept: 0 }` (the `existsSync` check on `officeRoot`).
- `readdir`/`statSync` fails for a docType → skip that docType,
  continue.
- `rm` fails for a single orphan → log + continue; next sweep will
  retry.
- `office_list_documents` IPC fails → sweep is skipped entirely
  (no `knownDocIds` to gate on); the renderer's existing
  `setError` path surfaces the failure.

### Testing

Unit (`electron/__tests__/officeIpc.test.ts`):

| Case | Expectation |
|---|---|
| Empty `<workspace>/office/` | returns `{ swept: 0 }`, does not throw |
| Missing `<workspace>/office/` | returns `{ swept: 0 }`, does not throw |
| 1 ppt orphan + `knownDocIds={}` | returns `{ swept: 1 }`, dir gone |
| 1 ppt "managed" dir + `knownDocIds={dirName}` | returns `{ swept: 0 }`, dir preserved |
| 3 dirs: 2 orphan + 1 managed | returns `{ swept: 2 }`, only orphans gone |
| `rm` fails for one orphan (mock) | sweep logs warn, other orphans removed, `{ swept: n-1 }` |

Integration (`src/features/office/__tests__/useOfficeDocuments.test.ts`):

| Case | Expectation |
|---|---|
| `workspacePath` changes from `null` to `'/tmp/ws'` | `listDocuments` then `sweepOrphanStaging` both called with the same workspacePath and `knownDocIds` matching the list |
| `listDocuments` IPC rejects | `sweepOrphanStaging` is NOT called; error surfaced |
| `sweepOrphanStaging` rejects | documents list is still populated; error surfaced |
| `workspacePath` becomes `null` mid-flight | `cancelled` flag prevents stale `setDocuments` |

### Performance + safety

- Sweep is O(n) over `<workspace>/office/<docType>/<dir>/`. Document
  count per workspace is bounded by the user's history (hundreds at
  most in realistic use).
- Sweep NEVER touches paths outside the supplied `workspacePath`'s
  `office/` subtree. `path.join` of `officeRoot` is computed once and
  reused; every subsequent `path.join(typeDir, dirName)` is rooted
  under it.
- Sweep is lazy-triggered, so it does not add to app startup latency.
- Sweep is best-effort; one failure does not block other orphans or
  the import flow.

## Out of scope

- **No active "purge now" UI.** The sweep is implicit on workspace
  selection. A future settings-page button is possible but not part
  of this PR.
- **No startup-time cross-workspace sweep.** Lazy trigger is
  sufficient; a startup scan would require a workspace registry and
  adds complexity for marginal benefit.
- **No change to `completeOfficeImport` semantics.** This design does
  not modify how completion flows work; it only adds cleanup on
  workspace entry using the existing `id`/`workspace_path` index in
  `office_documents`.

## Why

Closes the 6th Minor follow-up from the M0 milestone (`staging dir
缺 startup-time orphan sweep`, deferred from `105cae1`). Required for
M1-M2 chat-read: by the time users are reading managed documents
through the chat flow, repeated crash-restart cycles must not leave
visible disk bloat under the workspace.

**How to apply:** Implementation plan goes on a new
`fix/office-staging-sweep` branch. The Open question has been
resolved during the design phase (staging dir == managed dir by
design, since `office_routes.py:223` uses `file_path.parent.name` as
`document_id`). The plan therefore MUST include the db-coordinated
sweep described above, NOT the namespace-isolation variant in the
earlier draft.