# Preserve Chat Messages on Route Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent optimistic user and assistant messages from disappearing when the Chat page is unmounted and remounted while an LLM stream is in progress.

**Architecture:** Keep the existing module-singleton `useChatStreamStore` for active stream state, and make historical message loading in `useStore.loadMessages` merge backend results with local messages for the requested session. Backend messages win for duplicate IDs; local messages not yet persisted remain, preserving the stream's message IDs so `useChat` can write the final answer after the route returns.

**Tech Stack:** React 18, TypeScript, Zustand, Vitest, Testing Library, Vite.

## Global Constraints

- Do not modify backend APIs, database schema, Electron IPC protocol, or `release/win7`.
- Keep message updates immutable.
- Do not cancel an active chat stream when the Chat route unmounts.
- Run frontend tests and TypeScript/build checks using the repository's Node environment.
- Preserve existing error handling and `isLoading` behavior in `loadMessages`.
- Use Chinese progress and summary reports, while keeping code identifiers and test names consistent with repository conventions.

## File Map

- Modify `src/shared/lib/store.ts:133-143`: merge backend history with local messages during `loadMessages`.
- Keep the merge helper private in `src/shared/lib/store.ts`; no additional production file is needed.
- Modify `src/shared/lib/__tests__/store.test.ts`: add focused `loadMessages` merge coverage to the existing store test suite.
- Modify `src/features/send-message/__tests__/useChat.test.ts`: add a regression scenario proving an in-flight assistant message survives a reload and receives the final stream content.
- Update `docs/superpowers/specs/2026-08-20-preserve-chat-messages-on-route-switch-design.md` implementation checklist after implementation and verification.

### Task 1: Add failing store-level merge tests

**Files:**
- Test: `src/shared/lib/__tests__/store.test.ts`

**Interfaces:**
- Consumes: `useStore.loadMessages(sessionId)`, mocked `invoke`, and `Message` objects from `src/shared/lib/store.ts`.
- Produces: executable regression tests specifying exact merge behavior for later implementation.

- [ ] **Step 1: Run the existing store test file to confirm its setup.**

  Inspect its existing `desktopInvoke` mock and Zustand reset helpers before adding the new cases. Reuse that setup instead of introducing a second mocking convention.

- [ ] **Step 2: Write a failing test for preserving local messages missing from backend history.**

  Arrange the store with a current session and two local messages:

  ```ts
  const localUser: Message = {
    id: 'local-user',
    session_id: 'session-1',
    role: 'user',
    content: '仍在发送的问题',
    created_at: 1_000,
  };
  const localAssistant: Message = {
    id: 'local-assistant',
    session_id: 'session-1',
    role: 'assistant',
    content: '🤔 思考中…',
    created_at: 1_001,
  };
  useStore.setState({ currentSessionId: 'session-1', messages: [localUser, localAssistant] });
  invokeMock.mockResolvedValueOnce([]);
  ```

  Call `await useStore.getState().loadMessages('session-1')` and assert both local messages remain in order. The test must fail against the current unconditional `set({ messages })` implementation.

- [ ] **Step 3: Write a failing test for backend duplicate precedence and session isolation.**

  Arrange a local assistant with ID `assistant-1` containing the thinking placeholder, a backend message with the same ID containing `最终回复`, and a local message belonging to `session-2`. Mock the backend response with the duplicate assistant plus one historical message. Assert:

  - `assistant-1` appears once and has backend content `最终回复`;
  - the backend historical message remains;
  - the `session-2` local message is excluded;
  - ordering follows backend input order, followed by target-session local messages absent from backend; local message order remains stable.

- [ ] **Step 4: Run only the new tests and verify RED.**

  Run:

  ```bash
  npm exec vitest run src/shared/lib/__tests__/store.test.ts
  ```

  Expected: the new preservation assertion fails because `loadMessages` currently replaces the entire message list with the backend response.

### Task 2: Implement immutable message merge in the store

**Files:**
- Modify: `src/shared/lib/store.ts:133-143`
- Test: the store test file from Task 1

**Interfaces:**
- Consumes: backend `Message[]` returned by `invoke('get_messages', { sessionId })` and current Zustand `messages`.
- Produces: `loadMessages(sessionId)` that publishes a merged, session-scoped `Message[]` without mutating either input array.

- [ ] **Step 1: Define the merge behavior directly before editing.**

  Use these exact rules:

  ```ts
  function mergeLoadedMessages(
    loadedMessages: Message[],
    localMessages: Message[],
    sessionId: string,
  ): Message[] {
    // Start with backend messages, then append only local messages from this
    // session whose IDs are absent from the backend result.
    // Preserve backend input order; preserve local store order for appended messages.
  }
  ```

  The helper may remain private in `store.ts`. It must create new arrays and must not mutate `loadedMessages`, `localMessages`, or message objects.

- [ ] **Step 2: Implement the smallest production change.**

  Change `loadMessages` so the async response is applied through a functional Zustand update, preventing a stale closure from replacing messages added while `invoke` was in flight:

  ```ts
  const loadedMessages = await invoke<Message[]>('get_messages', { sessionId });
  set((state) => ({
    messages: mergeLoadedMessages(loadedMessages, state.messages, sessionId),
    isLoading: false,
  }));
  ```

  Keep the existing `try/catch`, logging, and `isLoading` reset behavior. Do not merge messages from another session.

- [ ] **Step 3: Run the store tests and verify GREEN.**

  Run:

  ```bash
  npm exec vitest run src/shared/lib/__tests__/store.test.ts
  ```

  Expected: all existing store tests and the new merge tests pass.

- [ ] **Step 4: Add an immutability assertion if the test setup permits it.**

  Freeze or snapshot the input arrays before calling the helper indirectly through `loadMessages`, then assert their contents are unchanged. Do not require object cloning because the merge reuses immutable `Message` objects and only creates a new array.

- [ ] **Step 5: Commit the focused store fix.**

  ```bash
  git add src/shared/lib/store.ts src/shared/lib/__tests__/store.test.ts
  git commit -m "fix: preserve optimistic messages during history reload"
  ```

### Task 3: Add the route-switch stream regression test

**Files:**
- Test: `src/features/send-message/__tests__/useChat.test.ts` (or the existing unmount test if its setup supports this scenario)

**Interfaces:**
- Consumes: `useChat.sendMessage`, `useStore.loadMessages`, `useChatStreamStore`, mocked `invoke`, and mocked stream listener callback.
- Produces: a regression test reproducing route unmount/remount timing and proving the final assistant response survives.

- [ ] **Step 1: Arrange a delayed stream callback and optimistic messages.**

  Follow the existing `persists streaming state for events arriving AFTER chatStream() resolves` setup. Capture the listener callback without immediately sending events. Start `sendMessage('ping')`, allow the `agent_chat_stream` IPC and listener registration to resolve, and assert the local user and assistant placeholder exist.

- [ ] **Step 2: Simulate Chat unmount and remount history loading.**

  Call `await useStore.getState().loadMessages(VALID_SESSION_ID)` while the mocked backend returns an older history list that excludes the newly-created local messages. Assert the store still contains both the local user message and assistant placeholder. This is the exact route-switch regression and should fail before Task 2.

- [ ] **Step 3: Simulate the final stream event and assert persistence in the active store.**

  Dispatch a `done` callback with `content: 'route switch answer'`. Assert the assistant message with the original ID now contains `route switch answer`, and `useChatStreamStore.getState().streaming` is cleared after finish.

- [ ] **Step 4: Run the focused regression tests.**

  Run:

  ```bash
  npm exec vitest run src/features/send-message/__tests__/useChat.test.ts src/features/send-message/__tests__/useChat.stream-survives-unmount.test.tsx
  ```

  Expected: all existing stream tests and the new route-switch test pass.

- [ ] **Step 5: Commit the regression coverage.**

  ```bash
  git add src/features/send-message/__tests__/useChat.test.ts src/features/send-message/__tests__/useChat.stream-survives-unmount.test.tsx
  git commit -m "test: cover chat stream across route reload"
  ```

### Task 4: Run complete verification and update design checklist

**Files:**
- Modify: `docs/superpowers/specs/2026-08-20-preserve-chat-messages-on-route-switch-design.md`

**Interfaces:**
- Consumes: completed store implementation and regression tests from Tasks 1–3.
- Produces: verified branch with updated implementation checklist and no unrelated changes.

- [ ] **Step 1: Run the complete frontend test suite.**

  ```bash
  npm exec vitest run
  ```

  Expected: all Vitest tests pass. If failures occur, stop and investigate the first failure rather than weakening tests.

- [ ] **Step 2: Run TypeScript and production build checks.**

  ```bash
  npm run typecheck
  npm run build
  ```

  Expected: both commands complete successfully.

- [ ] **Step 3: Inspect the final diff and check for forbidden changes.**

  ```bash
  git diff main...HEAD --stat
  git diff main...HEAD --check
  git status --short
  ```

  Confirm only the design/plan docs, store implementation, and focused tests changed. Confirm there are no `console.log` statements or hardcoded secrets in modified source files.

- [ ] **Step 4: Mark the design implementation steps complete.**

  Update the checklist in `docs/superpowers/specs/2026-08-20-preserve-chat-messages-on-route-switch-design.md`:

  ```md
  - [x] 为 `loadMessages` 增加“后端历史消息 + 未持久化本地消息”的回归测试
  - [x] 实现按消息 ID 的不可变合并逻辑
  - [x] 增加页面卸载/重新加载后流式回复仍能写回的测试覆盖
  - [x] 运行相关 Vitest 测试、TypeScript 检查和前端构建
  - [x] 运行代码审查并根据结果修正
  ```

- [ ] **Step 5: Run the mandatory code review agent before final completion.**

  Review the complete diff with the TypeScript/general code-review agents, address any CRITICAL or HIGH findings, then rerun the affected tests. Do not commit or claim completion until review findings are resolved or explicitly reported.

- [ ] **Step 6: Commit documentation and verification updates.**

  ```bash
  git add docs/superpowers/specs/2026-08-20-preserve-chat-messages-on-route-switch-design.md
  git commit -m "docs: record chat route switch fix verification"
  ```
