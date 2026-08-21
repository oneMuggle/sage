# Factory Cleanup Fix Report

Status: completed

## Change

`AgentTool._build_subagent()` now cleans the registry-owned 0700 scratch root when an injected `subagent_factory` raises during construction, then re-raises the original exception. Caller-provided workspace roots remain unowned and are not deleted.

Added a focused regression test covering factory construction failure and owned-root cleanup.

## Verification

- TDD red: new regression test failed before implementation because the captured scratch root still existed.
- Focused pytest: `18 passed, 5 warnings`
- Ruff: `All checks passed!`
- `git diff --check d732e971..HEAD`: passed
- Additional working-tree `git diff --check`: passed

## Commit

Implementation commit: `ab22f592c953e728aa5beecd9bfc15c976044629`

## Residual concerns

No known residual concerns for this lifecycle path. Normal, failed, timeout worker cleanup remains in `_run_subagent_async`; caller-provided workspace roots remain protected by the existing ownership marker.
