# Regression Tests (A29 from pi)

Regression tests are tied to specific GitHub issues to ensure bugs don't reappear.

## Naming Convention

```
regressions/<issue-number>-<short-slug>.test.ts
```

Examples:
- `regressions/123-chat-stream-failed.test.ts`
- `regressions/456-sidebar-crash.test.ts`
- `regressions/789-theme-flash.test.ts`

## Writing Regression Tests

1. **Reproduce the bug**: Write a test that fails with the old code
2. **Fix the bug**: Implement the fix
3. **Verify**: Test should pass
4. **Name it**: Use the issue number + short description

## Example

```typescript
// regressions/123-chat-stream-failed.test.ts
import { describe, it, expect } from 'vitest';

describe('Regression #123: chat stream FAILED state', () => {
  it('should handle FAILED state gracefully', () => {
    // Test that reproduces the bug
    // This should pass after the fix
  });
});
```

## Why This Matters

- **Traceability**: Every regression test links to a specific issue
- **Documentation**: Test names serve as living documentation
- **Prevention**: Ensures bugs don't silently reappear

From pi's testing strategy: `test/suite/regressions/<issue>-<slug>.test.ts`
