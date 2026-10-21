import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearLastWorkspacePath,
  getLastWorkspacePath,
  setLastWorkspacePath,
} from '../lastWorkspace';

describe('lastWorkspace — localStorage persistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns null when nothing is stored', () => {
    expect(getLastWorkspacePath()).toBeNull();
  });

  it('stores and retrieves a workspace path', () => {
    setLastWorkspacePath('/tmp/workspace-a');
    expect(getLastWorkspacePath()).toBe('/tmp/workspace-a');
  });

  it('overwrites previously stored path', () => {
    setLastWorkspacePath('/tmp/workspace-a');
    setLastWorkspacePath('/tmp/workspace-b');
    expect(getLastWorkspacePath()).toBe('/tmp/workspace-b');
  });

  it('clears the stored path', () => {
    setLastWorkspacePath('/tmp/workspace-a');
    clearLastWorkspacePath();
    expect(getLastWorkspacePath()).toBeNull();
  });

  it('returns null when localStorage.getItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => {
      throw new Error('disabled');
    });
    expect(getLastWorkspacePath()).toBeNull();
    spy.mockRestore();
  });

  it('does not throw when localStorage.setItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => {
      throw new Error('quota exceeded');
    });
    expect(() => setLastWorkspacePath('/tmp/ws')).not.toThrow();
    spy.mockRestore();
  });

  it('does not throw when localStorage.removeItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementationOnce(() => {
      throw new Error('disabled');
    });
    expect(() => clearLastWorkspacePath()).not.toThrow();
    spy.mockRestore();
  });
});

describe('lastWorkspace diagnostic formatters (Phase P114)', () => {
  it('formats last workspace summary and JSON payload', async () => {
    const { formatLastWorkspaceSummary, formatLastWorkspaceJson } = await import(
      '../lastWorkspace'
    );
    expect(formatLastWorkspaceSummary(null)).toBe('none');
    expect(formatLastWorkspaceSummary('/tmp/ws-1')).toBe('persisted · /tmp/ws-1');
    const parsed = JSON.parse(formatLastWorkspaceJson('/tmp/ws-1'));
    expect(parsed).toEqual({
      schema: 'sage.shared.last_workspace.v1',
      key: 'sage-last-workspace-path',
      persisted: true,
      workspacePath: '/tmp/ws-1',
    });
  });
});
