import { render } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import { PetFocusBridge } from '../PetFocusBridge';

const report = vi.fn();

function installBridge() {
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    pet: { reportFocusSession: report },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  report.mockReset();
  useStore.setState({ currentSessionId: null });
});

afterEach(() => {
  vi.useRealTimers();
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  useStore.setState({ currentSessionId: null });
});

describe('PetFocusBridge', () => {
  it('reports the current session after the debounce window', () => {
    installBridge();
    render(<PetFocusBridge />);
    act(() => {
      useStore.setState({ currentSessionId: 'sess-a' });
      vi.advanceTimersByTime(150);
    });
    expect(report).toHaveBeenLastCalledWith('sess-a');
  });

  it('coalesces rapid switches and ignores duplicates', () => {
    installBridge();
    render(<PetFocusBridge />);
    act(() => {
      useStore.setState({ currentSessionId: 'sess-a' });
      vi.advanceTimersByTime(100);
      useStore.setState({ currentSessionId: 'sess-b' });
      vi.advanceTimersByTime(150);
    });
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenLastCalledWith('sess-b');

    act(() => {
      useStore.setState({ currentSessionId: 'sess-b' });
      vi.advanceTimersByTime(150);
    });
    expect(report).toHaveBeenCalledTimes(1);
  });
});
