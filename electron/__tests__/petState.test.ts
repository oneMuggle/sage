import { describe, expect, it } from 'vitest';

import {
  applyEvent,
  applyMeta,
  classifyTool,
  createEmptyState,
  selectSnapshot,
  tick,
} from '../pet/state';

const T0 = 1_000_000;

describe('pet state reducer', () => {
  it('classifies tool names into pet details', () => {
    expect(classifyTool('bash')).toBe('bash');
    expect(classifyTool('read_file')).toBe('read');
    expect(classifyTool('edit')).toBe('edit');
    expect(classifyTool('web_search')).toBe('web');
    expect(classifyTool('mcp__zotero__search')).toBe('mcp');
    expect(classifyTool('office_create')).toBe('office');
    expect(classifyTool('unknown_tool')).toBe('other');
  });

  it('maps permission requests to the highest-priority waiting action', () => {
    let state = applyEvent(
      createEmptyState(),
      's1',
      { state: 'acting', tool_call: { function: { name: 'bash' } } },
      T0,
    );
    state = applyEvent(state, 's2', { state: 'thinking' }, T0 + 1);
    state = applyEvent(state, 's2', { state: 'permission_request' }, T0 + 2);
    const snapshot = selectSnapshot(state, T0 + 2);
    expect(snapshot.action).toBe('waiting');
    expect(snapshot.sessionId).toBe('s2');
    expect(snapshot.bubbleKey).toBe('waiting');
  });

  it('prefers error over done and acting', () => {
    let state = createEmptyState();
    state = applyEvent(
      state,
      's1',
      { state: 'acting', tool_call: { function: { name: 'edit' } } },
      T0,
    );
    state = applyEvent(state, 's2', { state: 'done' }, T0 + 1);
    state = applyEvent(state, 's3', { state: 'failed' }, T0 + 2);
    expect(selectSnapshot(state, T0 + 2).action).toBe('error');
  });

  it('decays terminal actions to idle after 45 seconds and keeps the last result', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'done' }, T0);
    expect(selectSnapshot(state, T0).action).toBe('done');
    state = tick(state, T0 + 44_999);
    expect(selectSnapshot(state, T0 + 44_999).action).toBe('done');
    state = tick(state, T0 + 45_000);
    const snapshot = selectSnapshot(state, T0 + 45_000);
    expect(snapshot.action).toBe('idle');
    expect(snapshot.lastTerminalAction).toBe('done');
    expect(snapshot.lastTerminalAt).toBe(T0);
  });

  it('tracks todo progress and the active todo', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'thinking' }, T0);
    state = applyEvent(
      state,
      's1',
      {
        state: 'todo_snapshot',
        todos: [
          { content: '调研', status: 'completed' },
          { content: '实现', status: 'completed' },
          { content: '写测试', status: 'in_progress' },
          { content: '文档', status: 'pending' },
          { content: '收尾', status: 'pending' },
        ],
      },
      T0 + 1,
    );
    const snapshot = selectSnapshot(state, T0 + 1);
    expect(snapshot.action).toBe('thinking');
    expect(snapshot.todoDone).toBe(2);
    expect(snapshot.todoTotal).toBe(5);
    expect(snapshot.todoActive).toBe('写测试');
    expect(snapshot.progressKind).toBe('todo');
    expect(snapshot.bubbleKey).toBe('todo');
  });

  it('tracks orchestration step progress without downgrading an active tool', () => {
    let state = applyEvent(
      createEmptyState(),
      's1',
      { state: 'acting', tool_call: { function: { name: 'edit' } } },
      T0,
    );
    state = applyEvent(state, 's1', { state: 'task_progress', total: 7, done: 3 }, T0 + 1);
    const snapshot = selectSnapshot(state, T0 + 1);
    expect(snapshot.action).toBe('acting');
    expect(snapshot.todoDone).toBe(3);
    expect(snapshot.todoTotal).toBe(7);
    expect(snapshot.progressKind).toBe('plan');
    // An active tool keeps its own bubble; progress only updates the meters.
    expect(snapshot.bubbleKey).toBe('tool_edit');
    state = applyEvent(state, 's1', { state: 'done' }, T0 + 2);
    expect(selectSnapshot(state, T0 + 2).todoDone).toBe(7);
  });

  it('merges session title and context metadata without touching the action', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'thinking' }, T0);
    state = applyMeta(
      state,
      's1',
      { sessionTitle: '写周报', contextUsed: 40_000, contextMax: 128_000 },
      T0 + 10,
    );
    const snapshot = selectSnapshot(state, T0 + 10);
    expect(snapshot.action).toBe('thinking');
    expect(snapshot.sessionTitle).toBe('写周报');
    expect(snapshot.contextUsed).toBe(40_000);
    expect(snapshot.contextMax).toBe(128_000);
    expect(snapshot.updatedAt).toBe(T0);
  });

  it('exposes multiple sessions for the panel, highest priority first', () => {
    let state = applyEvent(createEmptyState(), 'a', { state: 'thinking' }, T0);
    state = applyEvent(state, 'b', { state: 'permission_request' }, T0 + 1);
    state = applyEvent(state, 'c', { state: 'done' }, T0 + 2);
    const snapshot = selectSnapshot(state, T0 + 2);
    expect(snapshot.sessions.map((session) => session.sessionId)).toEqual(['b', 'a', 'c']);
    // done/c/idle are terminal states, not "active" work.
    expect(snapshot.activeSessions).toBe(2);
  });

  it('falls asleep after two minutes of inactivity', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'thinking' }, T0);
    state = applyEvent(state, 's1', { state: 'idle' }, T0 + 1);
    state = tick(state, T0 + 119_999);
    expect(selectSnapshot(state, T0 + 119_999).action).toBe('idle');
    state = tick(state, T0 + 120_001);
    expect(selectSnapshot(state, T0 + 120_001).action).toBe('sleeping');
  });

  it('heartbeats keep an active session awake without changing its action', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'thinking' }, T0);
    state = applyEvent(state, 's1', { state: 'heartbeat' }, T0 + 60_000);
    state = tick(state, T0 + 60_000);
    expect(selectSnapshot(state, T0 + 60_000).action).toBe('thinking');
  });

  it('keeps the most recently updated session on priority ties', () => {
    let state = applyEvent(createEmptyState(), 'old', { state: 'thinking' }, T0);
    state = applyEvent(state, 'new', { state: 'reasoning' }, T0 + 5);
    expect(selectSnapshot(state, T0 + 5).sessionId).toBe('new');
  });
});
