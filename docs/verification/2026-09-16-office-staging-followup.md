# Office staging follow-up (2026-09-16)

## Scope and baseline

- Existing audit PRs: main #903, release/win7 #904. No merge to either release branch is authorized or performed.
- Main upstream remains `91d5dd96`; Win7 upstream advanced to `4bd1618f` (version bump plus subprocess sandbox exit-code correction). Merged that Win7 baseline into its dedicated audit worktree before porting this follow-up.
- Earlier verification documents describe the previous heads, not this follow-up's CI results.

## Implemented

- Exclusive, best-effort ownership evidence on newly staged imports; immutable completion sentinel. Neither overwrites pre-existing metadata.
- Completion consumes the in-process token **before** asynchronous metadata I/O, so a concurrent discard cannot remove a completed import.
- Explicit Office-page read-only inspection with English/Chinese labels. No scan on mount; workspace changes and unmount invalidate late responses; older desktop bridges show an unsupported message.
- Retain active tokens, live/possibly-live owner PIDs (including PID reuse), completed imports, recent imports, unknown metadata, links and unreadable entries. No moving, quarantine or deletion is exposed by the scanner or UI.
- Seven days is a **review label only**, not a deletion policy. A dead process and old staging evidence do not prove that a document is orphaned: backend commit may have succeeded without the completion IPC arriving.
- Report limited to 1000 entries with a truncation notice. Group/workspace office links are not traversed. This is an inspection aid, not a complete forensic inventory or a security boundary against concurrent external filesystem mutation.

## Regression coverage

Targeted tests cover exclusive metadata creation, persistent completion, active/recent retention, unknown/malformed/oversized evidence, symlink retention, no filesystem mutation during preview, completion/discard interleaving, explicit UI invocation, stale workspace responses and old bridge compatibility.

## Remaining release gates

Audit item #10 remains **partially addressed**: dangerous sweep disabled; safe evidence/preview now implemented. A collector requires authoritative database-reference reconciliation, crash/concurrent-import safety, a separately approved quarantine/retention policy and recovery tests. No automatic permanent deletion has been implemented.

Real Windows 7 OS execution and installed-package startup/rollback scenarios remain external release gates; Python 3.8 CI is not Windows 7 OS certification. No environment was provided for these scenarios. Dependency installation was reused, not a clean install.

New-head local and CI results are recorded on the PRs after execution; do not reuse previous green checks as evidence for this change.
