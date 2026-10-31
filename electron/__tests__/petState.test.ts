import { describe, expect, it } from 'vitest';

import { applyEvent, classifyTool, createEmptyState, selectSnapshot, tick } from '../pet/state';

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

  it('decays terminal actions to idle after 8 seconds', () => {
    let state = applyEvent(createEmptyState(), 's1', { state: 'done' }, T0);
    expect(selectSnapshot(state, T0).action).toBe('done');
    state = tick(state, T0 + 7_999);
    expect(selectSnapshot(state, T0 + 7_999).action).toBe('done');
    state = tick(state, T0 + 8_000);
    expect(selectSnapshot(state, T0 + 8_000).action).toBe('idle');
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
