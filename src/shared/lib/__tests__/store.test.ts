import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockLoad, mockSave } = vi.hoisted(() => ({
  mockLoad: vi.fn(),
  mockSave: vi.fn(),
}));
vi.mock('../../../entities/session/storage', () => ({
  loadCurrentSessionId: (...args: unknown[]) => mockLoad(...args),
  saveCurrentSessionId: (...args: unknown[]) => mockSave(...args),
}));

import { useStore } from '../store';

describe('useStore currentSessionId async', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    useStore.setState({ currentSessionId: null });
  });

  it('setCurrentSessionId 调 saveCurrentSessionId 异步', async () => {
    mockSave.mockResolvedValue(undefined);
    useStore.getState().setCurrentSessionId('abc-123');
    expect(useStore.getState().currentSessionId).toBe('abc-123');
    await vi.waitFor(() => expect(mockSave).toHaveBeenCalledWith('abc-123'));
  });

  it('setCurrentSessionId(null) 同步清空', () => {
    useStore.setState({ currentSessionId: 'old' });
    useStore.getState().setCurrentSessionId(null);
    expect(useStore.getState().currentSessionId).toBeNull();
  });
});
