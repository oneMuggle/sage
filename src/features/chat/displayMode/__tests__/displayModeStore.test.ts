import { describe, it, expect, beforeEach, vi } from 'vitest';

import { displayModeStore, subscribeDisplayModeStore } from '../displayModeStore';

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

  it('notifies subscribers on set/clear and stops after unsubscribe', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeDisplayModeStore(listener);

    displayModeStore.setSession('session-1', 'detail');
    expect(listener).toHaveBeenCalledTimes(1);

    displayModeStore.clearSession('session-1');
    expect(listener).toHaveBeenCalledTimes(2);

    displayModeStore.setMessage('msg-1', 'result');
    displayModeStore.clearMessage('msg-1');
    expect(listener).toHaveBeenCalledTimes(4);

    unsubscribe();
    displayModeStore.setSession('session-2', 'trace');
    expect(listener).toHaveBeenCalledTimes(4);
  });
});
