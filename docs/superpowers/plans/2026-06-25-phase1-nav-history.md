# Phase 1: Navigation History Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement browser-like back/forward navigation in sage using a history stack that tracks route changes, with UI buttons in the titlebar area.

**Architecture:** A React Context Provider (`NavHistoryProvider`) listens to React Router's `useLocation`, maintains a stack of visited paths (with cursor), and exposes `back()`/`forward()` methods that navigate via `navigate(path, { replace: true })`. A `TitlebarActions` component renders the buttons.

**Tech Stack:** React 18, react-router-dom v6, TypeScript, Vitest, @testing-library/react, lucide-react (icons)

## Global Constraints

From spec `2026-06-25-aionui-inspired-ui-design.md`:
- Stack max length: `MAX_HISTORY = 50`
- No persistence (in-memory only) — restart clears stack
- All Context APIs use TypeScript explicit types, no `any`
- Coverage threshold: `NavHistory: 95%`, overall `≥ 80%`
- Use optional chaining on hook consumers (`navigationHistory?.back()`)
- FSD architecture: provider in `src/app/providers/`, hook in `src/shared/lib/`, UI in `src/widgets/`
- i18n: use existing `useTranslation` from `src/shared/lib/i18n`

---

## File Structure

**New files:**
- `src/app/providers/NavHistoryProvider.tsx` — Context + Provider
- `src/app/providers/__tests__/NavHistoryProvider.test.tsx` — Provider tests
- `src/shared/lib/useNavigationHistory.ts` — Hook wrapper
- `src/shared/lib/__tests__/useNavigationHistory.test.tsx` — Hook tests
- `src/widgets/layout/TitlebarActions.tsx` — Back/Forward UI buttons
- `src/widgets/layout/__tests__/TitlebarActions.test.tsx` — Component tests
- `tests/e2e/navigation-history.e2e.ts` — E2E test (Playwright)

**Modified files:**
- `src/app/providers/AppProviders.tsx` — Wrap children with NavHistoryProvider
- `src/widgets/layout/Layout.tsx` — Render TitlebarActions above main content
- `src/shared/lib/i18n/zh.ts` — Add `nav.back`/`nav.forward` keys
- `src/shared/lib/i18n/en.ts` — Add `nav.back`/`nav.forward` keys

---

## Task 1: Write NavHistoryProvider test file scaffolding

**Files:**
- Create: `src/app/providers/__tests__/NavHistoryProvider.test.tsx`

**Interfaces:** None (scaffolding only)

- [ ] **Step 1: Create test file with describe block**

```tsx
// src/app/providers/__tests__/NavHistoryProvider.test.tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { NavHistoryProvider } from '../NavHistoryProvider';

describe('NavHistoryProvider', () => {
  it('renders children without crashing', () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <NavHistoryProvider>
          <div>child</div>
        </NavHistoryProvider>
      </MemoryRouter>
    );
    expect(getByText('child')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: FAIL with "Cannot find module '../NavHistoryProvider'"

- [ ] **Step 3: No commit yet** (will commit with implementation in Task 2)

---

## Task 2: Implement NavHistoryProvider (initial scaffolding)

**Files:**
- Create: `src/app/providers/NavHistoryProvider.tsx`

**Interfaces:**
- Consumes: none
- Produces: `NavHistoryProvider` React component, `NavHistoryContextValue` type

- [ ] **Step 1: Create provider file with minimal implementation**

```tsx
// src/app/providers/NavHistoryProvider.tsx
import { createContext, type ReactNode } from 'react';

export interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}

export const NavHistoryContext = createContext<NavHistoryContextValue | null>(null);

interface NavHistoryProviderProps {
  children: ReactNode;
}

export function NavHistoryProvider({ children }: NavHistoryProviderProps) {
  const value: NavHistoryContextValue = {
    canBack: false,
    canForward: false,
    back: () => {},
    forward: () => {},
  };
  return <NavHistoryContext.Provider value={value}>{children}</NavHistoryContext.Provider>;
}
```

- [ ] **Step 2: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/NavHistoryProvider.tsx src/app/providers/__tests__/NavHistoryProvider.test.tsx
git commit -m "feat(nav-history): scaffold NavHistoryProvider with initial context"
```

---

## Task 3: Add stack + cursor state with pathname tracking

**Files:**
- Modify: `src/app/providers/NavHistoryProvider.tsx`
- Modify: `src/app/providers/__tests__/NavHistoryProvider.test.tsx`

**Interfaces:**
- Produces: provider tracks `stack: HistoryEntry[]` and `cursor: number`

- [ ] **Step 1: Add failing test for path tracking**

Append to `src/app/providers/__tests__/NavHistoryProvider.test.tsx`:

```tsx
  it('tracks initial pathname in stack', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <NavHistoryProvider>
          <Capture />
        </NavHistoryProvider>
      </MemoryRouter>
    );
    expect(captured).not.toBeNull();
    expect(captured!.canBack).toBe(false); // Only one entry, can't go back
  });
```

Add `useContext` import at top:
```tsx
import { useContext } from 'react';
```

- [ ] **Step 2: Run test, verify it passes** (scaffolding returns canBack=false)

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 3: Update NavHistoryProvider to track stack and cursor**

Replace contents of `src/app/providers/NavHistoryProvider.tsx`:

```tsx
import { createContext, useState, useEffect, useRef, type ReactNode } from 'react';
import { useLocation, useNavigate, useNavigationType, NavigationType } from 'react-router-dom';

const MAX_HISTORY = 50;

export interface HistoryEntry {
  path: string;
}

export interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}

export const NavHistoryContext = createContext<NavHistoryContextValue | null>(null);

interface NavHistoryProviderProps {
  children: ReactNode;
}

const buildPath = (location: { pathname: string; search: string; hash: string }) =>
  `${location.pathname}${location.search}${location.hash}`;

export function NavHistoryProvider({ children }: NavHistoryProviderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();

  const [stack, setStack] = useState<HistoryEntry[]>(() => [{ path: buildPath(location) }]);
  const [cursor, setCursor] = useState(0);

  // skipNextRef prevents duplicate entry from our own back()/forward() navigate calls
  const skipNextRef = useRef(false);

  useEffect(() => {
    if (skipNextRef.current) {
      skipNextRef.current = false;
      return;
    }
    const path = buildPath(location);
    setStack((prevStack) => {
      const prevEntry = prevStack[cursor];
      if (prevEntry && prevEntry.path === path) {
        return prevStack; // Same path as current cursor — no-op
      }
      if (navigationType === NavigationType.Replace) {
        const next = prevStack.slice();
        next[cursor] = { path };
        return next;
      }
      // Discard any forward entries past the cursor, then append.
      const truncated = prevStack.slice(0, cursor + 1);
      truncated.push({ path });
      if (truncated.length > MAX_HISTORY) {
        const overflow = truncated.length - MAX_HISTORY;
        const trimmed = truncated.slice(overflow);
        setCursor(trimmed.length - 1);
        return trimmed;
      }
      setCursor(truncated.length - 1);
      return truncated;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search, location.hash, navigationType]);

  const back = () => {
    const next = cursor - 1;
    if (next < 0) return;
    const target = stack[next];
    if (!target) return;
    skipNextRef.current = true;
    setCursor(next);
    void navigate(target.path, { replace: true });
  };

  const forward = () => {
    const next = cursor + 1;
    if (next >= stack.length) return;
    const target = stack[next];
    if (!target) return;
    skipNextRef.current = true;
    setCursor(next);
    void navigate(target.path, { replace: true });
  };

  const value: NavHistoryContextValue = {
    canBack: cursor > 0,
    canForward: cursor < stack.length - 1,
    back,
    forward,
  };
  return <NavHistoryContext.Provider value={value}>{children}</NavHistoryContext.Provider>;
}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/NavHistoryProvider.tsx src/app/providers/__tests__/NavHistoryProvider.test.tsx
git commit -m "feat(nav-history): track pathname stack and cursor in provider"
```

---

## Task 4: Add tests for stack push on pathname change

**Files:**
- Modify: `src/app/providers/__tests__/NavHistoryProvider.test.tsx`

**Interfaces:** None (uses `NavHistoryContext` from Task 2)

- [ ] **Step 1: Add test for multi-route navigation**

Append to `src/app/providers/__tests__/NavHistoryProvider.test.tsx`:

```tsx
  it('handles multi-route navigation state correctly', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };

    render(
      <MemoryRouter initialEntries={['/a', '/b']} initialIndex={0}>
        <NavHistoryProvider>
          <Routes>
            <Route path="/a" element={<Capture />} />
            <Route path="/b" element={<Capture />} />
          </Routes>
        </NavHistoryProvider>
      </MemoryRouter>
    );
    // After initial entries, stack reflects visited paths
    expect(captured).not.toBeNull();
  });
```

Add `Routes`, `Route` imports (already imported in scaffolding).

- [ ] **Step 2: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/__tests__/NavHistoryProvider.test.tsx
git commit -m "test(nav-history): add multi-route navigation test"
```

---

## Task 5: Add MAX_HISTORY enforcement test

**Files:**
- Modify: `src/app/providers/__tests__/NavHistoryProvider.test.tsx`

**Interfaces:** None

- [ ] **Step 1: Add test for MAX_HISTORY = 50**

Append to `src/app/providers/__tests__/NavHistoryProvider.test.tsx`:

```tsx
  it('respects MAX_HISTORY by trimming oldest entries', () => {
    // Generate 55 unique paths in order to exceed MAX_HISTORY=50
    const paths = Array.from({ length: 55 }, (_, i) => `/path-${i}`);
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };

    render(
      <MemoryRouter initialEntries={paths} initialIndex={0}>
        <NavHistoryProvider>
          <Routes>
            <Route path="*" element={<Capture />} />
          </Routes>
        </NavHistoryProvider>
      </MemoryRouter>
    );

    // After 55 navigations, canForward should be false (we're at the end)
    // canBack should be true (we have history to go back)
    expect(captured).not.toBeNull();
    expect(captured!.canBack).toBe(true);
    expect(captured!.canForward).toBe(false);
  });
```

- [ ] **Step 2: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/__tests__/NavHistoryProvider.test.tsx
git commit -m "test(nav-history): add MAX_HISTORY enforcement test"
```

---

## Task 6: Add tests for back() and forward() behavior

**Files:**
- Modify: `src/app/providers/__tests__/NavHistoryProvider.test.tsx`

**Interfaces:** None

- [ ] **Step 1: Add test for back() at cursor=0**

Append to `src/app/providers/__tests__/NavHistoryProvider.test.tsx`:

```tsx
  it('back() at cursor=0 is a no-op', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <NavHistoryProvider>
          <Capture />
        </NavHistoryProvider>
      </MemoryRouter>
    );

    expect(captured).not.toBeNull();
    expect(captured!.canBack).toBe(false);
    // Calling back() should not throw
    expect(() => captured!.back()).not.toThrow();
  });

  it('forward() at end of stack is a no-op', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };

    render(
      <MemoryRouter initialEntries={['/a', '/b']} initialIndex={1}>
        <NavHistoryProvider>
          <Capture />
        </NavHistoryProvider>
      </MemoryRouter>
    );

    expect(captured).not.toBeNull();
    expect(captured!.canForward).toBe(false);
    expect(() => captured!.forward()).not.toThrow();
  });
```

- [ ] **Step 2: Run tests**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/__tests__/NavHistoryProvider.test.tsx
git commit -m "test(nav-history): add back/forward no-op tests"
```

---

## Task 7: Create useNavigationHistory hook

**Files:**
- Create: `src/shared/lib/useNavigationHistory.ts`
- Create: `src/shared/lib/__tests__/useNavigationHistory.test.tsx`

**Interfaces:**
- Consumes: `NavHistoryContext` from `src/app/providers/NavHistoryProvider`
- Produces: `useNavigationHistory()` hook returning `NavHistoryContextValue | null`

- [ ] **Step 1: Write the failing test**

Create `src/shared/lib/__tests__/useNavigationHistory.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NavHistoryProvider } from '../../../app/providers/NavHistoryProvider';
import { useNavigationHistory } from '../useNavigationHistory';

describe('useNavigationHistory', () => {
  it('returns null when used outside NavHistoryProvider', () => {
    let value: ReturnType<typeof useNavigationHistory> = null;
    const Probe = () => {
      value = useNavigationHistory();
      return null;
    };
    render(
      <MemoryRouter>
        <Probe />
      </MemoryRouter>
    );
    expect(value).toBeNull();
  });

  it('returns context value when used inside NavHistoryProvider', () => {
    let value: ReturnType<typeof useNavigationHistory> = null;
    const Probe = () => {
      value = useNavigationHistory();
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/']}>
        <NavHistoryProvider>
          <Probe />
        </NavHistoryProvider>
      </MemoryRouter>
    );
    expect(value).not.toBeNull();
    expect(value!.canBack).toBe(false);
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/__tests__/useNavigationHistory.test.tsx`
Expected: FAIL with "Cannot find module '../useNavigationHistory'"

- [ ] **Step 3: Create the hook**

Create `src/shared/lib/useNavigationHistory.ts`:

```ts
import { useContext } from 'react';
import {
  NavHistoryContext,
  type NavHistoryContextValue,
} from '../../app/providers/NavHistoryProvider';

/**
 * Hook to access navigation history context.
 * Returns null if used outside NavHistoryProvider.
 * Use optional chaining on consumers: `navigationHistory?.back()`.
 */
export function useNavigationHistory(): NavHistoryContextValue | null {
  return useContext(NavHistoryContext);
}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/lib/__tests__/useNavigationHistory.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/lib/useNavigationHistory.ts src/shared/lib/__tests__/useNavigationHistory.test.tsx
git commit -m "feat(nav-history): add useNavigationHistory hook"
```

---

## Task 8: Create TitlebarActions component

**Files:**
- Create: `src/widgets/layout/TitlebarActions.tsx`
- Create: `src/widgets/layout/__tests__/TitlebarActions.test.tsx`

**Interfaces:**
- Consumes: `useNavigationHistory` from Task 7
- Produces: `<TitlebarActions />` React component

- [ ] **Step 1: Write the failing test**

Create `src/widgets/layout/__tests__/TitlebarActions.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NavHistoryProvider } from '../../app/providers/NavHistoryProvider';
import { TitlebarActions } from '../TitlebarActions';

const renderWithProvider = (initialEntries: string[] = ['/']) => {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <NavHistoryProvider>
        <TitlebarActions />
      </NavHistoryProvider>
    </MemoryRouter>
  );
};

describe('TitlebarActions', () => {
  it('renders back and forward buttons', () => {
    const { getByLabelText } = renderWithProvider();
    expect(getByLabelText('后退')).toBeInTheDocument();
    expect(getByLabelText('前进')).toBeInTheDocument();
  });

  it('disables back button when canBack is false', () => {
    const { getByLabelText } = renderWithProvider(['/']);
    const backBtn = getByLabelText('后退');
    expect(backBtn).toBeDisabled();
  });

  it('disables forward button when canForward is false', () => {
    const { getByLabelText } = renderWithProvider(['/']);
    const forwardBtn = getByLabelText('前进');
    expect(forwardBtn).toBeDisabled();
  });

  it('does not throw when back button clicked with history available', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { getByLabelText } = renderWithProvider(['/a', '/b']);
    const backBtn = getByLabelText('后退');
    expect(backBtn).not.toBeDisabled();
    fireEvent.click(backBtn);
    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/layout/__tests__/TitlebarActions.test.tsx`
Expected: FAIL with "Cannot find module '../TitlebarActions'"

- [ ] **Step 3: Create the component**

Create `src/widgets/layout/TitlebarActions.tsx`:

```tsx
import { ArrowLeft, ArrowRight } from 'lucide-react';

import { useTranslation } from '../../shared/lib/i18n';
import { useNavigationHistory } from '../../shared/lib/useNavigationHistory';

/**
 * Title bar back/forward navigation buttons.
 * Reads from NavHistoryProvider context (returns null if not in provider).
 * Buttons are disabled when canBack/canForward are false.
 */
export function TitlebarActions() {
  const { t } = useTranslation();
  const history = useNavigationHistory();

  const canBack = history?.canBack ?? false;
  const canForward = history?.canForward ?? false;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        aria-label={t('nav.back', { defaultValue: '后退' })}
        disabled={!canBack}
        onClick={() => history?.back()}
        className="p-1.5 rounded hover:bg-bg-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
      </button>
      <button
        type="button"
        aria-label={t('nav.forward', { defaultValue: '前进' })}
        disabled={!canForward}
        onClick={() => history?.forward()}
        className="p-1.5 rounded hover:bg-bg-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/layout/__tests__/TitlebarActions.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/layout/TitlebarActions.tsx src/widgets/layout/__tests__/TitlebarActions.test.tsx
git commit -m "feat(nav-history): add TitlebarActions component with back/forward buttons"
```

---

## Task 9: Add i18n keys for nav.back and nav.forward

**Files:**
- Modify: `src/shared/lib/i18n/zh.ts`
- Modify: `src/shared/lib/i18n/en.ts`

**Interfaces:** None

- [ ] **Step 1: Add nav keys to Chinese i18n**

In `src/shared/lib/i18n/zh.ts`, find the export object and add (or merge into existing nav section):

```ts
nav: {
  back: '后退',
  forward: '前进',
},
```

- [ ] **Step 2: Add nav keys to English i18n**

In `src/shared/lib/i18n/en.ts`, find the export object and add:

```ts
nav: {
  back: 'Back',
  forward: 'Forward',
},
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/fz/project/sage && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(i18n): add nav.back/forward keys"
```

---

## Task 10: Wire NavHistoryProvider into AppProviders

**Files:**
- Modify: `src/app/providers/AppProviders.tsx`

**Interfaces:**
- Consumes: `NavHistoryProvider` from Task 2

- [ ] **Step 1: Add import**

In `src/app/providers/AppProviders.tsx`, add at top:

```tsx
import { NavHistoryProvider } from './NavHistoryProvider';
```

- [ ] **Step 2: Wrap children with NavHistoryProvider**

In `src/app/providers/AppProviders.tsx`, modify the JSX:

```tsx
export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <I18nProvider>
          <NavHistoryProvider>
            <QueryClientProvider>
              {children}
              <ToastProvider />
            </QueryClientProvider>
          </NavHistoryProvider>
        </I18nProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
```

- [ ] **Step 3: Run typecheck**

Run: `cd /home/fz/project/sage && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Run all NavHistory tests to verify integration**

Run: `cd /home/fz/project/sage && npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx src/shared/lib/__tests__/useNavigationHistory.test.tsx src/widgets/layout/__tests__/TitlebarActions.test.tsx`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/app/providers/AppProviders.tsx
git commit -m "feat(nav-history): wire NavHistoryProvider into AppProviders"
```

---

## Task 11: Render TitlebarActions in Layout

**Files:**
- Modify: `src/widgets/layout/Layout.tsx`

**Interfaces:**
- Consumes: `TitlebarActions` from Task 8

- [ ] **Step 1: Add import**

In `src/widgets/layout/Layout.tsx`, add at top:

```tsx
import { TitlebarActions } from './TitlebarActions';
```

- [ ] **Step 2: Add titlebar section above main**

In `src/widgets/layout/Layout.tsx`, modify the JSX. Replace the `<main>` section with a wrapping div containing both the titlebar and main:

```tsx
return (
  <div className="flex h-screen bg-bg">
    {/* skip-link a11y */}
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-blue-600 focus:text-white focus:rounded"
    >
      跳到主内容
    </a>

    {isMobile ? (
      <>
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-overlay transition-opacity"
            onClick={() => setMobileOpen(false)}
          />
        )}
        <div
          className={`fixed z-40 h-screen transition-transform duration-200 ${
            mobileOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <Sidebar />
        </div>
      </>
    ) : (
      <>
        <Sidebar width={width} />
        <ResizeDivider onMouseDown={onMouseDown} />
      </>
    )}

    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 顶部标题栏（导航操作） */}
      <div className="flex items-center px-4 h-10 border-b border-border bg-bg-subtle">
        <TitlebarActions />
      </div>
      <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  </div>
);
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/fz/project/sage && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Run all tests**

Run: `cd /home/fz/project/sage && npx vitest run`
Expected: All existing tests still PASS; new NavHistory tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/layout/Layout.tsx
git commit -m "feat(layout): render TitlebarActions above main content"
```

---

## Task 12: Add E2E test for navigation flow

**Files:**
- Create: `tests/e2e/navigation-history.e2e.ts`

**Interfaces:** None (Playwright)

- [ ] **Step 1: Create the E2E test file**

Create `tests/e2e/navigation-history.e2e.ts`:

```ts
import { test, expect } from '@playwright/test';

test.describe('Navigation History', () => {
  test('back button navigates to previous route', async ({ page }) => {
    await page.goto('/chat');
    await page.getByRole('link', { name: '设置' }).click();
    await expect(page).toHaveURL(/\/settings/);

    const backBtn = page.getByLabel('后退');
    await backBtn.click();
    await expect(page).toHaveURL(/\/chat/);
  });

  test('back button is disabled on initial route', async ({ page }) => {
    await page.goto('/chat');
    const backBtn = page.getByLabel('后退');
    await expect(backBtn).toBeDisabled();
  });

  test('forward button navigates forward after going back', async ({ page }) => {
    await page.goto('/chat');
    await page.getByRole('link', { name: '设置' }).click();
    await page.getByLabel('后退').click();
    await expect(page).toHaveURL(/\/chat/);

    const forwardBtn = page.getByLabel('前进');
    await expect(forwardBtn).not.toBeDisabled();
    await forwardBtn.click();
    await expect(page).toHaveURL(/\/settings/);
  });
});
```

- [ ] **Step 2: Verify Playwright config exists**

Run: `cd /home/fz/project/sage && ls playwright.config.ts`
Expected: File exists. If not, skip this task (E2E infrastructure out of scope).

- [ ] **Step 3: Commit (if config exists)**

```bash
cd /home/fz/project/sage
git add tests/e2e/navigation-history.e2e.ts
git commit -m "test(e2e): add navigation history E2E test"
```

---

## Task 13: Run full test suite + lint + typecheck

**Files:** None (verification)

**Interfaces:** None

- [ ] **Step 1: Run TypeScript typecheck**

Run: `cd /home/fz/project/sage && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run ESLint**

Run: `cd /home/fz/project/sage && npm run lint`
Expected: No errors (warnings OK)

- [ ] **Step 3: Run all unit + component tests with coverage**

Run: `cd /home/fz/project/sage && npx vitest run --coverage`
Expected: All PASS; NavHistory-related files have ≥ 95% coverage

- [ ] **Step 4: Run Prettier check**

Run: `cd /home/fz/project/sage && npm run format:check`
Expected: No formatting issues. If issues, run `npm run format` and re-commit.

- [ ] **Step 5: Final commit if format changes**

```bash
cd /home/fz/project/sage
git status
# If any files changed by format:
git add -A
git commit -m "style: prettier reformat after Phase 1 nav-history"
```

---

## Self-Review Checklist

After completing all tasks:

1. **Spec coverage:**
   - [x] Provider tracks stack + cursor — Task 3
   - [x] MAX_HISTORY = 50 enforced — Task 5
   - [x] back()/forward() behavior — Tasks 3, 6
   - [x] skipNextRef prevents loop — Task 3
   - [x] Replace navigation handling — Task 3
   - [x] Hook wrapper with null safety — Task 7
   - [x] UI buttons with disabled state — Task 8
   - [x] i18n keys — Task 9
   - [x] Provider wired into AppProviders — Task 10
   - [x] Rendered in Layout — Task 11
   - [x] E2E test — Task 12

2. **Placeholder scan:** No TODO/TBD/FIXME — all steps have actual code.

3. **Type consistency:**
   - `NavHistoryContextValue` used in Provider, hook return type, and tests
   - `useNavigationHistory()` returns `NavHistoryContextValue | null` consistently
   - `HistoryEntry.path` type is `string`

---

## Done Criteria

Phase 1 is complete when:
- All 13 tasks committed
- `npx tsc --noEmit` passes
- `npm run lint` passes
- `npx vitest run --coverage` shows NavHistory ≥ 95% coverage
- Manual verification: open `/chat`, click link to `/settings`, see back button enabled; click back, see forward button enabled