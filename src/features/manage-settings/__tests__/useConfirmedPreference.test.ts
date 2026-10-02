import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { read, write } = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: { getPreferenceStrict: read, setPreferenceStrict: write },
}));
import { useConfirmedPreference } from '../useConfirmedPreference';
const options = {
  key: 'fallback_model' as const,
  initial: '',
  parse: (value: string | null) => value ?? '',
  serialize: (value: string) => value,
};
beforeEach(() => {
  read.mockReset().mockResolvedValue('confirmed');
  write.mockReset();
});
describe('confirmed preference updates', () => {
  it('does not show a desired safety value as effective before acknowledgement', async () => {
    let reject!: (error: Error) => void;
    write.mockImplementation(
      () =>
        new Promise<void>((_, fail) => {
          reject = fail;
        }),
    );
    const state = renderHook(() => useConfirmedPreference(options));
    await waitFor(() => expect(state.result.current.loaded).toBe(true));
    act(() => state.result.current.update('desired'));
    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(state.result.current.value).toBe('confirmed');
    act(() => reject(new Error('offline')));
    await waitFor(() => expect(state.result.current.status).toBe('error'));
    expect(state.result.current.value).toBe('confirmed');
  });
  it('serializes changes and prevents a stale failure from replacing the latest success', async () => {
    let failFirst!: (error: Error) => void;
    write
      .mockImplementationOnce(
        () =>
          new Promise<void>((_, fail) => {
            failFirst = fail;
          }),
      )
      .mockResolvedValueOnce(undefined);
    const state = renderHook(() => useConfirmedPreference({ ...options, optimistic: true }));
    await waitFor(() => expect(state.result.current.loaded).toBe(true));
    act(() => {
      state.result.current.update('first');
      state.result.current.update('second');
    });
    await waitFor(() => expect(write).toHaveBeenCalledTimes(1));
    act(() => failFirst(new Error('offline')));
    await waitFor(() => expect(state.result.current.status).toBe('saved'));
    expect(write.mock.calls.map((call) => call[1])).toEqual(['first', 'second']);
    expect(state.result.current.value).toBe('second');
  });
  it('exposes an unreadable setting instead of claiming defaults are confirmed', async () => {
    read.mockRejectedValueOnce(new Error('offline'));
    const state = renderHook(() => useConfirmedPreference(options));
    await waitFor(() => expect(state.result.current.status).toBe('error'));
    expect(state.result.current.loaded).toBe(false);
    await act(async () => {
      await state.result.current.reload();
    });
    expect(state.result.current.value).toBe('confirmed');
  });
});
