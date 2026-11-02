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
