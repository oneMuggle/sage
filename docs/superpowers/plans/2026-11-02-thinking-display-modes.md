# 思考过程展示档位（detail / trace / result）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide three display modes (detail / trace / result) for AI reasoning and tool execution in the chat area, allowing users to control how much process detail is shown while keeping hidden content expandable.

**Architecture:** Pure frontend rendering strategy with three-level scope resolution (global preference → session override → message override). Display mode is stored in sessionStorage + in-memory Map, resolved via pure function, and consumed by React components through a custom hook. Backend remains unchanged.

**Tech Stack:** React 18, TypeScript, Radix UI (DropdownMenu), sessionStorage, Zustand-like store pattern, Vitest for testing

**Spec:** `docs/plans/2026-11-02_thinking-display-modes.md`

## Global Constraints

- **Zero baseline elevation**: `Message.tsx` (806→≤807), `settingsRegistry.ts` (811→≤812), `settingsSearchEntries.ts` (846→≤847) must not exceed current baseline
- **Extraction over inlining**: When files are at baseline, extract code to new files rather than adding inline
- **Pure frontend**: No backend changes; all state in sessionStorage + memory Map
- **Test coverage ≥ 80%**: All new code must have unit tests
- **i18n required**: All user-facing strings must have zh/en translations
- **Fail-safe**: Invalid display mode values fall back to `trace` (default)

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `src/features/chat/displayMode/types.ts` | `DisplayMode` type, default value, option constants |
| `src/features/chat/displayMode/displayModeStore.ts` | Session/message override read/write (sessionStorage + memory Map) |
| `src/features/chat/displayMode/resolveDisplayMode.ts` | Pure function: three-level scope resolution + display contract |
| `src/features/chat/displayMode/useDisplayMode.ts` | React hook: subscribe to global/session/message overrides |
| `src/features/chat/displayMode/toolGrouping.ts` | Tool grouping logic extracted from `Message.tsx` |
| `src/features/chat/displayMode/__tests__/resolveDisplayMode.test.ts` | Unit tests for resolution + contract |
| `src/features/chat/displayMode/__tests__/displayModeStore.test.ts` | Unit tests for store read/write |
| `src/features/chat/displayMode/__tests__/toolGrouping.test.ts` | Unit tests for grouping logic |
| `src/pages/chat/DisplayModeSwitch.tsx` | Chat header display mode switcher (Radix DropdownMenu) |
| `src/entities/setting/settingFactories.ts` | Extracted factory functions from `settingsRegistry.ts` |
| `src/pages/settings/settingsSearchEntriesChat.ts` | Extracted chat-related search entries |
| `src/shared/lib/i18n/locales/zh/chatDisplayMode.ts` | Chinese translations |
| `src/shared/lib/i18n/locales/en/chatDisplayMode.ts` | English translations |

### Modified Files

| File | Change | Line Budget |
|---|---|---|
| `src/widgets/chat/Message.tsx` | Integrate display mode hook + contract; extract toolGrouping | 806 → ≤807 |
| `src/widgets/chat/MessageMarkdownParts.tsx` | Add `defaultExpanded` prop to `ThinkingPanel` | 645 (room: 155) |
| `src/widgets/chat/thinkingExpansionStore.ts` | Add `getThinkingExpanded()` | 57 (room: 743) |
| `src/widgets/chat/messageContextMenu.ts` | Add display mode submenu | 202 (room: 598) |
| `src/pages/chat/ChatHeaderBar.tsx` | Mount `DisplayModeSwitch` + update governance tuple | 146 (room: 654) |
| `src/pages/settings/BasicTab.tsx` | Add global default dropdown | 388 (room: 412) |
| `src/entities/setting/settingsRegistry.ts` | Extract factories + register `chat_display_mode` | 811 → ≤812 |
| `src/pages/settings/settingsSearchEntries.ts` | Extract chat entries + add new entry | 846 → ≤847 |
| `src/shared/api/settingsClient.ts` | Add `chat_display_mode` to `PreferenceKey` | 197 (room: 603) |
| `src/entities/setting/storage.ts` | Add `chat_display_mode` to `resetPreferencesToDefaults` | ~420 (room: plenty) |
| `src/shared/lib/i18n/zh.ts` | Spread new locale | — |
| `src/shared/lib/i18n/en.ts` | Spread new locale | — |

---

### Task 1: Types, Store, and Resolution (Pure Function Layer)

**Files:**
- Create: `src/features/chat/displayMode/types.ts`
- Create: `src/features/chat/displayMode/displayModeStore.ts`
- Create: `src/features/chat/displayMode/resolveDisplayMode.ts`
- Create: `src/features/chat/displayMode/__tests__/resolveDisplayMode.test.ts`
- Create: `src/features/chat/displayMode/__tests__/displayModeStore.test.ts`

**Interfaces:**
- Consumes: Nothing (foundation layer)
- Produces: `DisplayMode` type, `DEFAULT_DISPLAY_MODE`, `DISPLAY_MODE_VALUES`, `DisplayContract`, `resolveDisplayMode()`, `getDisplayContract()`, `displayModeStore` (get/set/clear for session/message), `useDisplayMode()` hook (used in Task 4)

- [x] **Step 1: Write failing tests for resolution logic**

Create `src/features/chat/displayMode/__tests__/resolveDisplayMode.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import {
  resolveDisplayMode,
  getDisplayContract,
  type DisplayMode,
} from '../resolveDisplayMode';

describe('resolveDisplayMode', () => {
  it('returns message override when present', () => {
    expect(
      resolveDisplayMode({
        messageOverride: 'result',
        sessionOverride: 'detail',
        globalDefault: 'trace',
      }),
    ).toBe('result');
  });

  it('falls back to session override when message is null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: 'detail',
        globalDefault: 'trace',
      }),
    ).toBe('detail');
  });

  it('falls back to global default when session and message are null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: null,
        globalDefault: 'detail',
      }),
    ).toBe('detail');
  });

  it('falls back to trace when all overrides are null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: null,
        globalDefault: null,
      }),
    ).toBe('trace');
  });

  it('falls back to trace on invalid value', () => {
    expect(
      resolveDisplayMode({
        messageOverride: 'invalid' as DisplayMode,
        sessionOverride: null,
        globalDefault: null,
      }),
    ).toBe('trace');
  });
});

describe('getDisplayContract', () => {
  it('detail mode: show thinking, auto-expand while streaming', () => {
    const contract = getDisplayContract('detail');
    expect(contract.showThinkingPanel).toBe(true);
    expect(contract.thinkingDefaultExpanded).toBe(true);
    expect(contract.autoExpandWhileStreaming).toBe(true);
    expect(contract.toolGroupThreshold).toBe(3);
    expect(contract.toolGroupDefaultExpanded).toBe(true);
  });

  it('trace mode: show thinking, default collapsed', () => {
    const contract = getDisplayContract('trace');
    expect(contract.showThinkingPanel).toBe(true);
    expect(contract.thinkingDefaultExpanded).toBe(false);
    expect(contract.autoExpandWhileStreaming).toBe(false);
    expect(contract.toolGroupThreshold).toBe(3);
  });

  it('result mode: hide thinking, group all tools', () => {
    const contract = getDisplayContract('result');
    expect(contract.showThinkingPanel).toBe(false);
    expect(contract.toolGroupThreshold).toBe(1);
    expect(contract.toolGroupDefaultExpanded).toBe(false);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/chat/displayMode/__tests__/resolveDisplayMode.test.ts`
Expected: FAIL with "Cannot find module"

- [x] **Step 3: Write minimal implementation for types and resolution**

Create `src/features/chat/displayMode/types.ts`:

```typescript
export type DisplayMode = 'detail' | 'trace' | 'result';

export const DEFAULT_DISPLAY_MODE: DisplayMode = 'trace';

export const DISPLAY_MODE_VALUES: readonly DisplayMode[] = ['detail', 'trace', 'result'];

export function isValidDisplayMode(value: unknown): value is DisplayMode {
  return (
    typeof value === 'string' &&
    (value === 'detail' || value === 'trace' || value === 'result')
  );
}
```

Create `src/features/chat/displayMode/resolveDisplayMode.ts`:

```typescript
import { DEFAULT_DISPLAY_MODE, isValidDisplayMode, type DisplayMode } from './types';

export interface DisplayModeInput {
  messageOverride?: DisplayMode | null;
  sessionOverride?: DisplayMode | null;
  globalDefault?: DisplayMode | null;
}

export interface DisplayContract {
  showThinkingPanel: boolean;
  thinkingDefaultExpanded: boolean;
  autoExpandWhileStreaming: boolean;
  toolGroupThreshold: number;
  toolGroupDefaultExpanded: boolean;
  toolCardDefaultCollapsed: boolean;
}

const CONTRACTS: Record<DisplayMode, DisplayContract> = {
  detail: {
    showThinkingPanel: true,
    thinkingDefaultExpanded: true,
    autoExpandWhileStreaming: true,
    toolGroupThreshold: 3,
    toolGroupDefaultExpanded: true,
    toolCardDefaultCollapsed: false,
  },
  trace: {
    showThinkingPanel: true,
    thinkingDefaultExpanded: false,
    autoExpandWhileStreaming: false,
    toolGroupThreshold: 3,
    toolGroupDefaultExpanded: true,
    toolCardDefaultCollapsed: true,
  },
  result: {
    showThinkingPanel: false,
    thinkingDefaultExpanded: false,
    autoExpandWhileStreaming: false,
    toolGroupThreshold: 1,
    toolGroupDefaultExpanded: false,
    toolCardDefaultCollapsed: true,
  },
};

export function resolveDisplayMode(input: DisplayModeInput): DisplayMode {
  const { messageOverride, sessionOverride, globalDefault } = input;
  if (messageOverride && isValidDisplayMode(messageOverride)) return messageOverride;
  if (sessionOverride && isValidDisplayMode(sessionOverride)) return sessionOverride;
  if (globalDefault && isValidDisplayMode(globalDefault)) return globalDefault;
  return DEFAULT_DISPLAY_MODE;
}

export function getDisplayContract(mode: DisplayMode): DisplayContract {
  return CONTRACTS[mode] ?? CONTRACTS[DEFAULT_DISPLAY_MODE];
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/features/chat/displayMode/__tests__/resolveDisplayMode.test.ts`
Expected: PASS

- [x] **Step 5: Write failing tests for store**

Create `src/features/chat/displayMode/__tests__/displayModeStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { displayModeStore } from '../displayModeStore';

describe('displayModeStore', () => {
  beforeEach(() => {
    sessionStorage.clear();
    displayModeStore.clearAll();
  });

  it('returns null when no override exists', () => {
    expect(displayModeStore.getSession('session-1')).toBeNull();
    expect(displayModeStore.getMessage('msg-1')).toBeNull();
  });

  it('stores and retrieves session override', () => {
    displayModeStore.setSession('session-1', 'detail');
    expect(displayModeStore.getSession('session-1')).toBe('detail');
  });

  it('stores and retrieves message override', () => {
    displayModeStore.setMessage('msg-1', 'result');
    expect(displayModeStore.getMessage('msg-1')).toBe('result');
  });

  it('clears session override', () => {
    displayModeStore.setSession('session-1', 'detail');
    displayModeStore.clearSession('session-1');
    expect(displayModeStore.getSession('session-1')).toBeNull();
  });

  it('message override is independent of session override', () => {
    displayModeStore.setSession('session-1', 'detail');
    displayModeStore.setMessage('msg-1', 'result');
    expect(displayModeStore.getSession('session-1')).toBe('detail');
    expect(displayModeStore.getMessage('msg-1')).toBe('result');
  });
});
```

- [x] **Step 6: Run tests to verify they fail**

Run: `npx vitest run src/features/chat/displayMode/__tests__/displayModeStore.test.ts`
Expected: FAIL with "Cannot find module"

- [x] **Step 7: Write minimal implementation for store**

Create `src/features/chat/displayMode/displayModeStore.ts`:

```typescript
import { isValidDisplayMode, type DisplayMode } from './types';

const SESSION_PREFIX = 'sage:display-mode:session:';
const MESSAGE_PREFIX = 'sage:display-mode:message:';

const memory = new Map<string, DisplayMode>();

function readStorage(key: string): DisplayMode | null {
  const cached = memory.get(key);
  if (cached !== undefined) return cached;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw && isValidDisplayMode(raw)) {
      memory.set(key, raw);
      return raw;
    }
  } catch {
    /* sessionStorage unavailable */
  }
  return null;
}

function writeStorage(key: string, value: DisplayMode): void {
  memory.set(key, value);
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* sessionStorage unavailable */
  }
}

function deleteStorage(key: string): void {
  memory.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* sessionStorage unavailable */
  }
}

export const displayModeStore = {
  getSession(sessionId: string): DisplayMode | null {
    return readStorage(SESSION_PREFIX + sessionId);
  },

  setSession(sessionId: string, mode: DisplayMode): void {
    writeStorage(SESSION_PREFIX + sessionId, mode);
  },

  clearSession(sessionId: string): void {
    deleteStorage(SESSION_PREFIX + sessionId);
  },

  getMessage(messageId: string): DisplayMode | null {
    return readStorage(MESSAGE_PREFIX + messageId);
  },

  setMessage(messageId: string, mode: DisplayMode): void {
    writeStorage(MESSAGE_PREFIX + messageId, mode);
  },

  clearMessage(messageId: string): void {
    deleteStorage(MESSAGE_PREFIX + messageId);
  },

  clearAll(): void {
    memory.clear();
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key && (key.startsWith(SESSION_PREFIX) || key.startsWith(MESSAGE_PREFIX))) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach((k) => sessionStorage.removeItem(k));
    } catch {
      /* sessionStorage unavailable */
    }
  },
};
```

- [x] **Step 8: Run tests to verify they pass**

Run: `npx vitest run src/features/chat/displayMode/__tests__/displayModeStore.test.ts`
Expected: PASS

- [x] **Step 9: Commit**

```bash
git add src/features/chat/displayMode/
git commit -m "feat(display-mode): add types, store, and resolution logic

- DisplayMode type with three modes: detail, trace, result
- displayModeStore for session/message overrides (sessionStorage + memory)
- resolveDisplayMode pure function with three-level scope resolution
- getDisplayContract pure function deriving rendering contract
- Unit tests for resolution and store"
```

---

### Task 2: Tool Grouping Extraction + Message.tsx Integration

**Files:**
- Create: `src/features/chat/displayMode/toolGrouping.ts`
- Create: `src/features/chat/displayMode/__tests__/toolGrouping.test.ts`
- Modify: `src/widgets/chat/Message.tsx:181-215` (extract tool grouping), then integrate display mode

**Interfaces:**
- Consumes: `DisplayMode`, `DisplayContract` from Task 1
- Produces: `canGroupToolCalls()`, `toolGroupSummary()`, `toolGroupOwners()` functions

- [x] **Step 1: Write failing tests for tool grouping**

Create `src/features/chat/displayMode/__tests__/toolGrouping.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { canGroupToolCalls, toolGroupSummary } from '../toolGrouping';
import type { ToolCall } from '../../../shared/lib/store';

describe('canGroupToolCalls', () => {
  const makeToolCall = (name: string, overrides: Partial<ToolCall> = {}): ToolCall => ({
    id: `tc-${name}`,
    name,
    args: {},
    result: 'ok',
    ...overrides,
  });

  it('returns false when streaming', () => {
    const tools = [makeToolCall('read'), makeToolCall('write'), makeToolCall('bash')];
    expect(canGroupToolCalls(tools, true, 3, {})).toBe(false);
  });

  it('returns false when tool count < threshold', () => {
    const tools = [makeToolCall('read'), makeToolCall('write')];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns true when tool count >= threshold and no special tools', () => {
    const tools = [makeToolCall('read'), makeToolCall('write'), makeToolCall('bash')];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(true);
  });

  it('returns false when any tool has blockReason', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('web_access', { metadata: { blockReason: 'blocked' } }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has imageData', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('diagram', { metadata: { imageData: 'data:image/png;base64,...' } }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has mediaRefs', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('media', { metadata: { mediaRefs: [{ id: 'm1' }] } }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has artifacts', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('code', { id: 'tc-code' }),
    ];
    const artifacts = { 'tc-code': [{ id: 'a1' }] };
    expect(canGroupToolCalls(tools, false, 3, artifacts)).toBe(false);
  });

  it('returns true with threshold=1 in result mode', () => {
    const tools = [makeToolCall('read')];
    expect(canGroupToolCalls(tools, false, 1, {})).toBe(true);
  });
});

describe('toolGroupSummary', () => {
  it('returns empty string when cannot group', () => {
    expect(toolGroupSummary([], false, 3)).toBe('');
  });

  it('summarizes tool counts', () => {
    const tools = [
      { name: 'read' },
      { name: 'write' },
      { name: 'bash' },
    ] as ToolCall[];
    expect(toolGroupSummary(tools, true, 3)).toBe('read · write · bash');
  });

  it('shows count for repeated tools', () => {
    const tools = [
      { name: 'read' },
      { name: 'read' },
      { name: 'write' },
    ] as ToolCall[];
    expect(toolGroupSummary(tools, true, 3)).toBe('read×2 · write');
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/chat/displayMode/__tests__/toolGrouping.test.ts`
Expected: FAIL with "Cannot find module"

- [x] **Step 3: Write minimal implementation for tool grouping**

Create `src/features/chat/displayMode/toolGrouping.ts`:

```typescript
import type { Artifact } from '../../artifacts/artifactApi';
import type { ToolCall } from '../../../shared/lib/store';

export function hasSpecialToolCalls(
  toolCalls: ToolCall[],
  artifactsByToolCall: Record<string, Artifact[]> | undefined,
): boolean {
  return toolCalls.some(
    (tc) =>
      Boolean(tc.metadata?.blockReason) ||
      Boolean(tc.metadata?.imageData) ||
      Boolean(tc.metadata?.mediaRefs?.length) ||
      Boolean(tc.id && artifactsByToolCall?.[tc.id]?.length),
  );
}

export function canGroupToolCalls(
  toolCalls: ToolCall[],
  isStreaming: boolean,
  threshold: number,
  artifactsByToolCall: Record<string, Artifact[]> | undefined,
): boolean {
  if (isStreaming) return false;
  if (toolCalls.length < threshold) return false;
  if (hasSpecialToolCalls(toolCalls, artifactsByToolCall)) return false;
  return true;
}

export function toolGroupSummary(
  toolCalls: ToolCall[],
  canGroup: boolean,
  _threshold: number,
): string {
  if (!canGroup) return '';
  const counts = new Map<string, number>();
  for (const tc of toolCalls) {
    counts.set(tc.name, (counts.get(tc.name) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .slice(0, 3)
    .map(([name, cnt]) => (cnt > 1 ? `${name}×${cnt}` : name))
    .join(' · ');
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/features/chat/displayMode/__tests__/toolGrouping.test.ts`
Expected: PASS

- [x] **Step 5: Refactor Message.tsx to use extracted tool grouping**

In `src/widgets/chat/Message.tsx`, replace lines 181-204 with:

```typescript
import { canGroupToolCalls, toolGroupSummary } from '../../features/chat/displayMode/toolGrouping';

// ... inside MessageComponent ...

const [toolGroupExpanded, setToolGroupExpanded] = useState(false);
const canGroup = useMemo(
  () => canGroupToolCalls(toolCalls, isStreaming, 3, artifactsByToolCall),
  [toolCalls, isStreaming, artifactsByToolCall],
);
const summary = useMemo(
  () => toolGroupSummary(toolCalls, canGroup, 3),
  [toolCalls, canGroup],
);
```

And update references from `canGroupToolCalls` → `canGroup`, `toolGroupSummary` → `summary`.

- [x] **Step 6: Run Message.tsx tests to verify no regression**

Run: `npx vitest run src/widgets/chat`
Expected: PASS

- [x] **Step 7: Integrate display mode hook into Message.tsx**

Add to `Message.tsx`:

```typescript
import { useDisplayMode } from '../../features/chat/displayMode/useDisplayMode';
import { getDisplayContract } from '../../features/chat/displayMode/resolveDisplayMode';

// ... inside MessageComponent ...

const { mode } = useDisplayMode(message.session_id, message.id);
const contract = useMemo(() => getDisplayContract(mode), [mode]);

const canGroup = useMemo(
  () => canGroupToolCalls(toolCalls, isStreaming, contract.toolGroupThreshold, artifactsByToolCall),
  [toolCalls, isStreaming, contract.toolGroupThreshold, artifactsByToolCall],
);

// Initialize toolGroupExpanded with contract default
const [toolGroupExpanded, setToolGroupExpanded] = useState(contract.toolGroupDefaultExpanded);
```

Update ThinkingPanel rendering:

```typescript
{isAssistant && message.reasoning_content && contract.showThinkingPanel && (
  <ThinkingPanel
    reasoning={message.reasoning_content}
    isStreaming={isStreaming}
    defaultExpanded={contract.thinkingDefaultExpanded}
  />
)}
```

- [x] **Step 8: Run architecture check**

Run: `node scripts/architecture-check.mjs`
Expected: PASS (Message.tsx should be ≤807 lines)

- [x] **Step 9: Commit**

```bash
git add src/features/chat/displayMode/toolGrouping.ts src/features/chat/displayMode/__tests__/toolGrouping.test.ts src/widgets/chat/Message.tsx
git commit -m "feat(display-mode): extract tool grouping and integrate into Message

- Extract canGroupToolCalls/toolGroupSummary to toolGrouping.ts
- Integrate useDisplayMode hook and DisplayContract
- Use contract.toolGroupThreshold for grouping decision
- Pass defaultExpanded to ThinkingPanel"
```

---

### Task 3: ThinkingPanel Default Expanded + Variant Key

**Files:**
- Modify: `src/widgets/chat/thinkingExpansionStore.ts`
- Modify: `src/widgets/chat/MessageMarkdownParts.tsx` (ThinkingPanel component)
- Create: `src/widgets/chat/__tests__/thinkingExpansionStore.test.ts`

**Interfaces:**
- Consumes: `DisplayMode` from Task 1
- Produces: `getThinkingExpanded(key)` returning `boolean | undefined`

> **Sequencing note (added after Task 2):** Task 2 pulled forward
> `getThinkingExpanded()` (Step 3 below) and the `ThinkingPanel.defaultExpanded`
> prop (Step 5 below) so the tree builds. Do **not** re-create them — verify they
> exist, then implement what Task 2 deliberately left here:
> (a) auto-expand must be gated on the mode (`autoExpandWhileStreaming`), not
> `if (isStreaming)` unconditionally;
> (b) the **variant key** `${displayMode}:${thinkingExpansionKey(reasoning)}` so
> each mode remembers its own expand state (`ThinkingPanel` needs a `mode` prop,
> and `Message.tsx` passes the resolved mode);
> (c) tests for `getThinkingExpanded` and the streaming behavior.
> Steps 1–5 stay as the reference for the already-created pieces.

- [x] **Step 1: Write failing tests for getThinkingExpanded**

Create `src/widgets/chat/__tests__/thinkingExpansionStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import {
  getThinkingExpanded,
  setThinkingExpanded,
  thinkingExpansionKey,
} from '../thinkingExpansionStore';

describe('getThinkingExpanded', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('returns undefined when never set', () => {
    const key = thinkingExpansionKey('test reasoning');
    expect(getThinkingExpanded(key)).toBeUndefined();
  });

  it('returns true after explicit expand', () => {
    const key = thinkingExpansionKey('test reasoning');
    setThinkingExpanded(key, true);
    expect(getThinkingExpanded(key)).toBe(true);
  });

  it('returns false after explicit collapse', () => {
    const key = thinkingExpansionKey('test reasoning');
    setThinkingExpanded(key, false);
    expect(getThinkingExpanded(key)).toBe(false);
  });

  it('distinguishes explicit false from undefined', () => {
    const key = thinkingExpansionKey('test reasoning');
    expect(getThinkingExpanded(key)).toBeUndefined();
    setThinkingExpanded(key, false);
    expect(getThinkingExpanded(key)).toBe(false);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/widgets/chat/__tests__/thinkingExpansionStore.test.ts`
Expected: FAIL with "getThinkingExpanded is not exported"

- [x] **Step 3: Implement getThinkingExpanded**

Modify `src/widgets/chat/thinkingExpansionStore.ts`, add:

```typescript
export function getThinkingExpanded(key: string): boolean | undefined {
  const cached = memory.get(key);
  if (cached !== undefined) return cached;
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
    if (raw === '1') {
      memory.set(key, true);
      return true;
    }
    if (raw === '0') {
      memory.set(key, false);
      return false;
    }
  } catch {
    /* sessionStorage unavailable */
  }
  return undefined;
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/widgets/chat/__tests__/thinkingExpansionStore.test.ts`
Expected: PASS

- [x] **Step 5: Update ThinkingPanel to accept defaultExpanded prop**

Modify `src/widgets/chat/MessageMarkdownParts.tsx`, update `ThinkingPanel`:

```typescript
export function ThinkingPanel({
  reasoning,
  isStreaming,
  defaultExpanded = false,
}: {
  reasoning: string;
  isStreaming?: boolean;
  defaultExpanded?: boolean;
}) {
  const baseKey = thinkingExpansionKey(reasoning);
  const [isExpanded, setIsExpanded] = useState(() => {
    const explicit = getThinkingExpanded(baseKey);
    return explicit !== undefined ? explicit : defaultExpanded;
  });

  // ... rest of component ...

  // Update auto-expand logic to respect defaultExpanded
  useEffect(() => {
    if (isStreaming && defaultExpanded) {
      setIsExpanded(true);
      setThinkingExpanded(baseKey, true, false);
    }
  }, [isStreaming, baseKey, defaultExpanded]);

  // ... rest unchanged ...
}
```

- [x] **Step 6: Run all widget tests**

Run: `npx vitest run src/widgets/chat`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/widgets/chat/thinkingExpansionStore.ts src/widgets/chat/MessageMarkdownParts.tsx src/widgets/chat/__tests__/thinkingExpansionStore.test.ts
git commit -m "feat(display-mode): add getThinkingExpanded and defaultExpanded prop

- Add getThinkingExpanded() returning boolean | undefined
- ThinkingPanel accepts defaultExpanded prop
- Explicit user choice takes precedence over default
- Auto-expand only when defaultExpanded is true"
```

---

### Task 4: useDisplayMode Hook

**Files:**
- Create: `src/features/chat/displayMode/useDisplayMode.ts`
- Create: `src/features/chat/displayMode/globalDisplayModePreference.ts`
- Modify: `src/features/chat/displayMode/displayModeStore.ts` (add subscription)
- Create: `src/features/chat/displayMode/__tests__/useDisplayMode.test.tsx`

**Interfaces:**
- Consumes: `displayModeStore`, `resolveDisplayMode` from Task 1
- Produces: `useDisplayMode(sessionId, messageId)` hook returning `{ mode, setSessionMode, setMessageMode, clearSessionMode, clearMessageMode }`

> **Sequencing note (added after Task 2):** a first cut of `useDisplayMode.ts`
> already exists (pulled forward by Task 2). This task **replaces** it. Two
> defects found in that cut must be fixed here:
> 1. `displayModeStore` reads are unsubscribed — switching the mode in an already
>    mounted `Message` would not re-render. Add a listener set + version counter
>    to `displayModeStore` and subscribe via `useSyncExternalStore`.
> 2. `useConfirmedPreference` inside the hook performs one IPC read **per
>    message**. Replace with the module-level shared store
>    `globalDisplayModePreference.ts` (one lazy read per app, reloaded on the
>    `sage:setting-changed` event for `chat_display_mode`).
> The settings page still writes through `useConfirmedPreference` directly; its
> `setPreferenceStrict` dispatches `sage:setting-changed`, which reloads the
> shared store, so both surfaces stay in sync.

- [x] **Step 1: Write the hook implementation**

Create `src/features/chat/displayMode/globalDisplayModePreference.ts`:

```typescript
/**
 * Module-level shared source for the global `chat_display_mode` preference.
 *
 * One lazy IPC read per app (not one per Message), reloaded whenever
 * `setPreferenceStrict('chat_display_mode', ...)` dispatches
 * `sage:setting-changed`. Consumers subscribe with `useSyncExternalStore`.
 */
import { settingsClient } from '../../../shared/api/settingsClient';

import { DEFAULT_DISPLAY_MODE, isValidDisplayMode, type DisplayMode } from './types';

let snapshot: DisplayMode = DEFAULT_DISPLAY_MODE;
let loaded = false;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();
let wired = false;

function emit(): void {
  for (const listener of listeners) listener();
}

async function load(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const raw = await settingsClient.getPreferenceStrict('chat_display_mode');
      snapshot = isValidDisplayMode(raw) ? raw : DEFAULT_DISPLAY_MODE;
    } catch {
      /* keep the current snapshot (default or last known good) */
    } finally {
      loaded = true;
      inflight = null;
      emit();
    }
  })();
  return inflight;
}

function onSettingChanged(event: Event): void {
  const detail = (event as CustomEvent<{ key?: string }>).detail;
  if (detail?.key === 'chat_display_mode') void load();
}

function ensureWired(): void {
  if (wired || typeof window === 'undefined') return;
  wired = true;
  window.addEventListener('sage:setting-changed', onSettingChanged);
}

export function subscribeGlobalDisplayMode(listener: () => void): () => void {
  ensureWired();
  listeners.add(listener);
  if (!loaded && !inflight) void load();
  return () => {
    listeners.delete(listener);
  };
}

export function getGlobalDisplayModeSnapshot(): DisplayMode {
  return snapshot;
}

/** Test-only: restore module state between tests. */
export function __resetGlobalDisplayModeForTests(): void {
  snapshot = DEFAULT_DISPLAY_MODE;
  loaded = false;
  inflight = null;
  listeners.clear();
  if (wired) {
    window.removeEventListener('sage:setting-changed', onSettingChanged);
    wired = false;
  }
}
```

Add subscription support to `src/features/chat/displayMode/displayModeStore.ts`:

```typescript
type DisplayModeListener = () => void;
const listeners = new Set<DisplayModeListener>();
let version = 0;

function emit(): void {
  version += 1;
  for (const listener of listeners) listener();
}

export function subscribeDisplayModeStore(listener: DisplayModeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getDisplayModeStoreVersion(): number {
  return version;
}
```

Call `emit()` at the end of every mutating method: `setSession`, `clearSession`,
`setMessage`, `clearMessage`, `clearAll`.

Create `src/features/chat/displayMode/useDisplayMode.ts`:

```typescript
import { useCallback, useMemo, useSyncExternalStore } from 'react';

import {
  displayModeStore,
  getDisplayModeStoreVersion,
  subscribeDisplayModeStore,
} from './displayModeStore';
import {
  getGlobalDisplayModeSnapshot,
  subscribeGlobalDisplayMode,
} from './globalDisplayModePreference';
import { resolveDisplayMode, type DisplayMode } from './resolveDisplayMode';

export function useDisplayMode(sessionId: string | null, messageId: string | null) {
  const storeVersion = useSyncExternalStore(
    subscribeDisplayModeStore,
    getDisplayModeStoreVersion,
    getDisplayModeStoreVersion,
  );
  const globalDefault = useSyncExternalStore(
    subscribeGlobalDisplayMode,
    getGlobalDisplayModeSnapshot,
    getGlobalDisplayModeSnapshot,
  );

  const sessionOverride = useMemo(
    () => (sessionId ? displayModeStore.getSession(sessionId) : null),
    [sessionId, storeVersion],
  );
  const messageOverride = useMemo(
    () => (messageId ? displayModeStore.getMessage(messageId) : null),
    [messageId, storeVersion],
  );

  const mode = useMemo(
    () => resolveDisplayMode({ messageOverride, sessionOverride, globalDefault }),
    [messageOverride, sessionOverride, globalDefault],
  );

  const setSessionMode = useCallback(
    (m: DisplayMode) => {
      if (sessionId) displayModeStore.setSession(sessionId, m);
    },
    [sessionId],
  );

  const clearSessionMode = useCallback(() => {
    if (sessionId) displayModeStore.clearSession(sessionId);
  }, [sessionId]);

  const setMessageMode = useCallback(
    (m: DisplayMode) => {
      if (messageId) displayModeStore.setMessage(messageId, m);
    },
    [messageId],
  );

  const clearMessageMode = useCallback(() => {
    if (messageId) displayModeStore.clearMessage(messageId);
  }, [messageId]);

  return { mode, setSessionMode, clearSessionMode, setMessageMode, clearMessageMode };
}
```

Add `src/features/chat/displayMode/__tests__/useDisplayMode.test.tsx` covering:
- a mounted consumer re-renders after `setSessionMode` / `setMessageMode` (the
  regression this task fixes);
- message override beats session override; `clearMessageMode` falls back;
- the global value loads once and is shared across two hook instances
  (`getPreferenceStrict` called exactly once);
- a `sage:setting-changed` event with `detail.key === 'chat_display_mode'`
  triggers exactly one reload;
- `beforeEach` calls `__resetGlobalDisplayModeForTests()` + `displayModeStore.clearAll()`.

- [x] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add src/features/chat/displayMode/useDisplayMode.ts
git commit -m "feat(display-mode): add useDisplayMode hook

- Subscribe to global preference via useConfirmedPreference
- Read session/message overrides from displayModeStore
- Resolve effective mode via resolveDisplayMode
- Provide setters/clearers for session and message overrides"
```

---

### Task 5: DisplayModeSwitch Component + ChatHeaderBar Integration

**Files:**
- Create: `src/pages/chat/DisplayModeSwitch.tsx`
- Modify: `src/pages/chat/ChatHeaderBar.tsx`

**Interfaces:**
- Consumes: `useDisplayMode` from Task 4, `DisplayMode` from Task 1
- Produces: `DisplayModeSwitch` React component

- [x] **Step 1: Write DisplayModeSwitch component**

Create `src/pages/chat/DisplayModeSwitch.tsx`:

```typescript
import { Brain, ChevronDown } from 'lucide-react';
import { useState } from 'react';

import { useDisplayMode } from '../../features/chat/displayMode/useDisplayMode';
import { DISPLAY_MODE_VALUES, type DisplayMode } from '../../features/chat/displayMode/types';
import { useI18n } from '../../shared/lib/i18n';

interface DisplayModeSwitchProps {
  sessionId: string | null;
}

const MODE_LABELS: Record<DisplayMode, string> = {
  detail: 'chat.displayMode.detail',
  trace: 'chat.displayMode.trace',
  result: 'chat.displayMode.result',
};

export function DisplayModeSwitch({ sessionId }: DisplayModeSwitchProps) {
  const { t } = useI18n();
  const { mode, setSessionMode, clearSessionMode } = useDisplayMode(sessionId, null);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="relative" data-testid="display-mode-switch">
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        data-testid="display-mode-button"
        className="flex items-center gap-1 px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
        title={t('chat.displayMode.label')}
      >
        <Brain className="w-3.5 h-3.5" aria-hidden />
        <span>{t(MODE_LABELS[mode])}</span>
        <ChevronDown className="w-3 h-3 opacity-60" aria-hidden />
      </button>

      {menuOpen && (
        <div
          role="menu"
          data-testid="display-mode-menu"
          className="absolute right-0 top-full mt-1 z-30 w-48 rounded border border-border bg-surface shadow-lg p-1"
        >
          {DISPLAY_MODE_VALUES.map((m) => {
            const active = m === mode;
            return (
              <button
                key={m}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                data-testid={`display-mode-${m}`}
                onClick={() => {
                  setSessionMode(m);
                  setMenuOpen(false);
                }}
                className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-xs hover:bg-bg-hover ${
                  active ? 'bg-primary/10 text-primary' : 'text-text'
                }`}
              >
                <Brain className="w-3.5 h-3.5 shrink-0" aria-hidden />
                <span>{t(MODE_LABELS[m])}</span>
              </button>
            );
          })}
          <div className="border-t border-border my-1" />
          <button
            type="button"
            role="menuitem"
            data-testid="display-mode-follow-global"
            onClick={() => {
              clearSessionMode();
              setMenuOpen(false);
            }}
            className="w-full text-left px-2 py-1.5 rounded text-xs text-text-secondary hover:bg-bg-hover"
          >
            {t('chat.displayMode.followGlobal')}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [x] **Step 2: Mount DisplayModeSwitch in ChatHeaderBar**

Modify `src/pages/chat/ChatHeaderBar.tsx`:

Add import:

```typescript
import { DisplayModeSwitch } from './DisplayModeSwitch';
```

Add component after orch-mode select, before SessionSettingsMenu:

```typescript
<DisplayModeSwitch sessionId={currentSessionId} />
<SessionSettingsMenu sessionId={currentSessionId} />
```

- [x] **Step 3: Update governance tuple**

Modify `auditChatHeaderBarGovernance` in `ChatHeaderBar.tsx`:

```typescript
export function auditChatHeaderBarGovernance(): {
  module: 'src/pages/chat/ChatHeaderBar.tsx';
  phase: 'P172';
  domain: 'chat';
  topHeaderControls: readonly [
    'SessionModelPicker',
    'OrchModeSelect',
    'DisplayModeSwitch',  // NEW
    'SessionSettingsMenu',
    'SessionSessionMenu',
    'RightPanelToggle',
  ];
  compliant: boolean;
} {
  return {
    module: 'src/pages/chat/ChatHeaderBar.tsx',
    phase: 'P172',
    domain: 'chat',
    topHeaderControls: [
      'SessionModelPicker',
      'OrchModeSelect',
      'DisplayModeSwitch',
      'SessionSettingsMenu',
      'SessionSessionMenu',
      'RightPanelToggle',
    ],
    compliant: true,
  };
}
```

- [x] **Step 4: Run ChatHeaderBar tests**

Run: `npx vitest run src/pages/chat`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/pages/chat/DisplayModeSwitch.tsx src/pages/chat/ChatHeaderBar.tsx
git commit -m "feat(display-mode): add DisplayModeSwitch to chat header

- Radix DropdownMenu with three modes + follow-global option
- Mount in ChatHeaderBar after orch-mode select
- Update governance tuple to include DisplayModeSwitch"
```

---

### Task 6: Settings Registry + Search Entries Extraction

**Files:**
- Create: `src/entities/setting/settingFactories.ts`
- Create: `src/pages/settings/settingsSearchEntriesChat.ts`
- Modify: `src/entities/setting/settingsRegistry.ts` (extract factories + register new key)
- Modify: `src/pages/settings/settingsSearchEntries.ts` (extract chat entries + add new entry)
- Modify: `src/shared/api/settingsClient.ts` (add to PreferenceKey)
- Modify: `src/entities/setting/storage.ts` (add to resetPreferencesToDefaults)

**Interfaces:**
- Consumes: `DisplayMode` from Task 1
- Produces: `settingFactories` (re-exported), `settingsSearchEntriesChat` (spread into main index)

- [x] **Step 1: Extract setting factories**

Create `src/entities/setting/settingFactories.ts`:

```typescript
import type { SettingMetadata } from './metadata';

export const booleanSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: boolean,
  applyMode: SettingMetadata['applyMode'] = 'immediate',
  visibility: SettingMetadata['visibility'] = 'basic',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'low',
  constraints: { type: 'boolean' },
});

export const numberSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: number,
  min: number,
  max?: number,
  applyMode: SettingMetadata['applyMode'] = 'next-request',
  visibility: SettingMetadata['visibility'] = 'advanced',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'medium',
  constraints: { type: 'number', min, ...(max === undefined ? {} : { max }) },
});

export const enumSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: string,
  options: Array<{ value: string; label: string }>,
  applyMode: SettingMetadata['applyMode'] = 'immediate',
  visibility: SettingMetadata['visibility'] = 'basic',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'low',
  constraints: { type: 'enum', options },
});

export const orchNumber = (
  key: string,
  label: string,
  description: string,
  defaultValue: number,
  min: number,
  max?: number,
): SettingMetadata => ({
  ...numberSetting(key, label, description, 'app_settings', defaultValue, min, max, 'next-run'),
  storageKey: key,
});
```

- [x] **Step 2: Update settingsRegistry.ts to use extracted factories**

Modify `src/entities/setting/settingsRegistry.ts`, replace lines 10-86 with:

```typescript
import { booleanSetting, numberSetting, enumSetting, orchNumber } from './settingFactories';

// Re-export for backward compatibility
export { booleanSetting, numberSetting, enumSetting, orchNumber };
```

- [x] **Step 3: Register chat_display_mode in settingsRegistry**

Add to `settingsRegistry` object:

```typescript
chat_display_mode: enumSetting(
  'chat_display_mode',
  'settings.basic.chat_display_mode_label',
  'settings.basic.chat_display_mode_desc',
  'preference',
  'trace',
  [
    { value: 'detail', label: 'settings.basic.chat_display_mode_detail' },
    { value: 'trace', label: 'settings.basic.chat_display_mode_trace' },
    { value: 'result', label: 'settings.basic.chat_display_mode_result' },
  ],
  'immediate',
  'basic',
),
```

- [x] **Step 4: Add to PreferenceKey**

> **Sequencing note (added after Task 2):** already done — `'chat_display_mode'`
> is present in `PreferenceKey` (`src/shared/api/settingsClient.ts`) and in the
> backend whitelist (`backend/data/settings_repo.py` `SettingsRepository.KEYS`).
> Verify both, skip the edit. Do not duplicate the union member.

Modify `src/shared/api/settingsClient.ts`, add to `PreferenceKey` union:

```typescript
| 'chat_display_mode'
```

- [x] **Step 5: Add to resetPreferencesToDefaults**

Modify `src/entities/setting/storage.ts`, add to `resetPreferencesToDefaults()`:

```typescript
settingsClient.setPreference('chat_display_mode', 'trace', 'ui'),
```

- [x] **Step 6: Extract chat search entries**

Create `src/pages/settings/settingsSearchEntriesChat.ts`:

```typescript
import type { SettingsSearchEntry } from './settingsSearchEntries';

export const CHAT_SETTINGS_SEARCH_ENTRIES: SettingsSearchEntry[] = [
  {
    key: 'streaming',
    tab: 'basic',
    label: '流式输出',
    labelEn: 'Streaming output',
    keywords: 'streaming 流式 输出 stream',
  },
  {
    key: 'chat_display_mode',
    tab: 'basic',
    label: '思考展示档位',
    labelEn: 'Reasoning display mode',
    keywords: 'chat_display_mode 思考 展示 档位 display mode reasoning thinking',
  },
  // ... (move other chat-related entries from main file)
];
```

- [x] **Step 7: Update settingsSearchEntries.ts to use extracted entries**

Modify `src/pages/settings/settingsSearchEntries.ts`, add import and spread:

```typescript
import { CHAT_SETTINGS_SEARCH_ENTRIES } from './settingsSearchEntriesChat';

export const SETTINGS_SEARCH_INDEX: SettingsSearchEntry[] = [
  // ... other entries ...
  ...CHAT_SETTINGS_SEARCH_ENTRIES,
  // ... rest ...
];
```

- [x] **Step 8: Run architecture check**

Run: `node scripts/architecture-check.mjs`
Expected: PASS (all files within baseline)

- [x] **Step 9: Run settings tests**

Run: `npx vitest run src/pages/settings src/entities/setting`
Expected: PASS

- [x] **Step 10: Commit**

```bash
git add src/entities/setting/ src/pages/settings/ src/shared/api/settingsClient.ts
git commit -m "feat(display-mode): register chat_display_mode setting

- Extract setting factories to settingFactories.ts (zero-baseline fix)
- Extract chat search entries to settingsSearchEntriesChat.ts
- Register chat_display_mode enum setting with preference storage
- Add to PreferenceKey union and resetPreferencesToDefaults
- Add search entry for chat_display_mode"
```

---

### Task 7: BasicTab Settings UI

**Files:**
- Modify: `src/pages/settings/BasicTab.tsx`

**Interfaces:**
- Consumes: `chat_display_mode` setting from Task 6, i18n keys from Task 8
- Produces: Dropdown UI for global default display mode

- [x] **Step 1: Add display mode dropdown to BasicTab**

Modify `src/pages/settings/BasicTab.tsx`, add import:

```typescript
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import type { DisplayMode } from '../../features/chat/displayMode/types';
```

Add component inside `BasicTab`:

```typescript
const displayModePref = useConfirmedPreference<DisplayMode>({
  key: 'chat_display_mode',
  initial: 'trace',
  parse: (value) => (value === 'detail' || value === 'trace' || value === 'result' ? value : 'trace'),
  serialize: (value) => value,
  category: 'ui',
});

// ... in JSX, after streaming toggle ...

<SettingRow
  label={t('settings.basic.chat_display_mode_label')}
  description={t('settings.basic.chat_display_mode_desc')}
>
  <select
    value={displayModePref.value}
    onChange={(e) => displayModePref.update(e.target.value as DisplayMode)}
    className="px-2 py-1 text-ui-xs border rounded-radius-sm outline-none"
  >
    <option value="detail">{t('chat.displayMode.detail')}</option>
    <option value="trace">{t('chat.displayMode.trace')}</option>
    <option value="result">{t('chat.displayMode.result')}</option>
  </select>
</SettingRow>
```

- [x] **Step 2: Run BasicTab tests**

Run: `npx vitest run src/pages/settings`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add src/pages/settings/BasicTab.tsx
git commit -m "feat(display-mode): add global default dropdown to BasicTab

- useConfirmedPreference for chat_display_mode
- Dropdown with three mode options
- Integrated into BasicTab settings UI"
```

---

### Task 8: i18n Translations

**Files:**
- Create: `src/shared/lib/i18n/locales/zh/chatDisplayMode.ts`
- Create: `src/shared/lib/i18n/locales/en/chatDisplayMode.ts`
- Modify: `src/shared/lib/i18n/zh.ts`
- Modify: `src/shared/lib/i18n/en.ts`

**Interfaces:**
- Consumes: Nothing
- Produces: Translation keys for display mode UI

- [x] **Step 1: Create Chinese translations**

Create `src/shared/lib/i18n/locales/zh/chatDisplayMode.ts`:

```typescript
export const zhChatDisplayMode = {
  'chat.displayMode.label': '思考展示',
  'chat.displayMode.detail': '详细思考',
  'chat.displayMode.trace': '仅执行',
  'chat.displayMode.result': '仅结果',
  'chat.displayMode.followGlobal': '跟随全局默认',
  'chat.displayMode.hiddenSummary': '已隐藏思考过程与 {count} 步工具调用',
  'chat.displayMode.reveal': '展开',
  'settings.basic.chat_display_mode_label': '思考展示档位',
  'settings.basic.chat_display_mode_desc': '控制聊天中思考过程与工具执行的展示密度',
  'settings.basic.chat_display_mode_detail': '详细思考',
  'settings.basic.chat_display_mode_trace': '仅执行',
  'settings.basic.chat_display_mode_result': '仅结果',
};
```

- [x] **Step 2: Create English translations**

Create `src/shared/lib/i18n/locales/en/chatDisplayMode.ts`:

```typescript
export const enChatDisplayMode = {
  'chat.displayMode.label': 'Reasoning display',
  'chat.displayMode.detail': 'Detailed',
  'chat.displayMode.trace': 'Execution',
  'chat.displayMode.result': 'Result only',
  'chat.displayMode.followGlobal': 'Follow global default',
  'chat.displayMode.hiddenSummary': 'Hidden reasoning and {count} tool calls',
  'chat.displayMode.reveal': 'Reveal',
  'settings.basic.chat_display_mode_label': 'Reasoning display mode',
  'settings.basic.chat_display_mode_desc': 'Controls how much reasoning and tool execution detail is shown',
  'settings.basic.chat_display_mode_detail': 'Detailed',
  'settings.basic.chat_display_mode_trace': 'Execution',
  'settings.basic.chat_display_mode_result': 'Result only',
};
```

- [x] **Step 3: Integrate into zh.ts**

Modify `src/shared/lib/i18n/zh.ts`, add:

```typescript
import { zhChatDisplayMode } from './locales/zh/chatDisplayMode';

export const zh = {
  ...zhChatAndSider,
  ...zhChatDisplayMode,
  // ... rest
};
```

- [x] **Step 4: Integrate into en.ts**

Modify `src/shared/lib/i18n/en.ts`, add:

```typescript
import { enChatDisplayMode } from './locales/en/chatDisplayMode';

export const en = {
  ...enChatAndSider,
  ...enChatDisplayMode,
  // ... rest
};
```

- [x] **Step 5: Run typecheck**

Run: `npm run typecheck`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/shared/lib/i18n/
git commit -m "feat(display-mode): add i18n translations

- Chinese and English translations for display mode UI
- Settings page labels and descriptions
- Integrated into zh.ts and en.ts"
```

---

### Task 9: Message Context Menu (Message-Level Override)

**Files:**
- Modify: `src/widgets/chat/messageContextMenu.ts`

**Interfaces:**
- Consumes: `displayModeStore` from Task 1, i18n keys from Task 8
- Produces: Submenu with four checkbox items for message-level override

- [x] **Step 1: Add display mode submenu to context menu**

Modify `src/widgets/chat/messageContextMenu.ts`, add import:

```typescript
import { displayModeStore } from '../features/chat/displayMode/displayModeStore';
import type { DisplayMode } from '../features/chat/displayMode/types';
```

Add to `MessageContextMenuParams`:

```typescript
messageId?: string;
sessionId?: string;
```

Add submenu in `buildMessageContextMenuItems`:

```typescript
if (isAssistant && message.id) {
  const currentMode = displayModeStore.getMessage(message.id);
  const sessionMode = message.session_id ? displayModeStore.getSession(message.session_id) : null;

  items.push({
    id: 'display-mode-submenu',
    label: t('chat.displayMode.label'),
    icon: Brain,
    submenu: [
      {
        id: 'display-mode-detail',
        label: t('chat.displayMode.detail'),
        kind: 'checkbox',
        checked: currentMode === 'detail',
        onCheckedChange: () => displayModeStore.setMessage(message.id!, 'detail'),
      },
      {
        id: 'display-mode-trace',
        label: t('chat.displayMode.trace'),
        kind: 'checkbox',
        checked: currentMode === 'trace',
        onCheckedChange: () => displayModeStore.setMessage(message.id!, 'trace'),
      },
      {
        id: 'display-mode-result',
        label: t('chat.displayMode.result'),
        kind: 'checkbox',
        checked: currentMode === 'result',
        onCheckedChange: () => displayModeStore.setMessage(message.id!, 'result'),
      },
      { id: 'display-mode-sep', kind: 'separator' },
      {
        id: 'display-mode-follow-session',
        label: sessionMode ? `跟随会话 (${t(`chat.displayMode.${sessionMode}`)})` : t('chat.displayMode.followGlobal'),
        kind: 'checkbox',
        checked: currentMode === null,
        onCheckedChange: () => displayModeStore.clearMessage(message.id!),
      },
    ],
  });
}
```

- [x] **Step 2: Update Message.tsx to pass messageId**

Modify `src/widgets/chat/Message.tsx`, in `buildContextMenuItems`:

```typescript
return buildMessageContextMenuItems({
  message,
  t,
  isStreaming,
  messageId: message.id,
  sessionId: message.session_id,
  // ... rest
});
```

- [x] **Step 3: Run message menu tests**

Run: `npx vitest run src/widgets/chat`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add src/widgets/chat/messageContextMenu.ts src/widgets/chat/Message.tsx
git commit -m "feat(display-mode): add message-level override to context menu

- Submenu with four options: detail, trace, result, follow-session
- Checkbox items show current selection
- Follow-session clears message override"
```

---

### Task 10: Full Verification + Documentation

**Files:**
- Modify: `docs/plans/2026-11-02_thinking-display-modes.md` (mark milestones complete)

- [x] **Step 1: Run full test suite**

Run: `npx vitest run`
Expected: PASS

- [x] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: PASS

- [x] **Step 3: Run architecture check**

Run: `node scripts/architecture-check.mjs`
Expected: PASS

- [x] **Step 4: Run pre-push verification**

Run: `npm run verify:pre-push`
Expected: PASS

- [x] **Step 5: End-to-end smoke coverage**

Platform checkout has no manual desktop session, so the eight smoke points are
covered by `tests/electron/tiers/stub/smoke/display-mode.spec.ts`
(header switch + default `trace` label + switch to `detail` + reload persistence
+ follow-global reset + assistant right-click submenu) and by component/unit
tests (`DisplayModeSwitch`, `messageContextMenu`, `BasicTab`, `Message.displayMode`):
1. Three modes switchable from chat header — e2e Steps 1–2
2. detail: thinking panel expanded, tools expanded — `ThinkingPanel` + contract tests
3. trace: thinking collapsed, tools expanded — default e2e label + `Message` tests
4. result: thinking hidden, tools in one expandable summary — `Message.displayMode` tests
5. Settings page dropdown changes global default — `BasicTab` + `useDisplayMode` tests
6. Context menu overrides single message — e2e Step 5 + `messageContextMenu` tests
7. Session override persists across page reload — e2e Step 3
8. Message override independent of session — `resolveDisplayMode` priority tests

- [x] **Step 6: Update documents**

Per repo convention, the design spec `docs/plans/2026-11-02_thinking-display-modes.md`
was merged into `docs/technical/125-thinking-display-modes.md` +
`docs/user-manual/31-thinking-display-modes.md` and then deleted.
This execution plan is retained with all milestones marked complete.

- [x] **Step 7: Final commit**

```bash
git add docs/
git commit -m "docs(display-mode): 新增技术手册 §123 与用户手册 §30"
```

---

## Execution Checklist

- [x] Task 1: Types, Store, Resolution (pure functions)
- [x] Task 2: Tool Grouping + Message.tsx Integration
- [x] Task 3: ThinkingPanel Default Expanded
- [x] Task 4: useDisplayMode Hook
- [x] Task 5: DisplayModeSwitch + ChatHeaderBar
- [x] Task 6: Settings Registry + Search Entries
- [x] Task 7: BasicTab UI
- [x] Task 8: i18n Translations
- [x] Task 9: Message Context Menu
- [x] Task 10: Full Verification + Documentation
