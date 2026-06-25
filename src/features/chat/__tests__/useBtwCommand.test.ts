import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBtwCommand } from '../useBtwCommand';
import { useBtwState } from '../../../entities/chat/btwState';

// Mock useChat hook
const mockAskBtw = vi.fn();
vi.mock('../../send-message/useChat', () => ({
  useChat: () => ({
    askBtw: mockAskBtw,
    sendMessage: vi.fn(),
    isLoading: false,
    messages: [],
    error: null,
    clearError: vi.fn(),
  }),
}));

describe('useBtwCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset BtwState to initial
    useBtwState.getState().close();
  });

  it('should initialize with closed state', () => {
    const { result } = renderHook(() => useBtwCommand());

    expect(result.current.isOpen).toBe(false);
    expect(result.current.question).toBe('');
    expect(result.current.answer).toBe('');
    expect(result.current.isLoading).toBe(false);
  });

  it('should open with question and call askBtw', () => {
    const { result } = renderHook(() => useBtwCommand());
    const question = 'What is useEffect?';

    act(() => {
      result.current.open(question);
    });

    expect(result.current.isOpen).toBe(true);
    expect(result.current.question).toBe(question);
    expect(mockAskBtw).toHaveBeenCalledWith(question);
  });

  it('should close and reset state', () => {
    const { result } = renderHook(() => useBtwCommand());

    act(() => {
      result.current.open('Test question');
    });

    expect(result.current.isOpen).toBe(true);

    act(() => {
      result.current.close();
    });

    expect(result.current.isOpen).toBe(false);
    expect(result.current.question).toBe('');
    expect(result.current.answer).toBe('');
    expect(result.current.isLoading).toBe(false);
  });

  it('should reflect BtwState changes', () => {
    const { result } = renderHook(() => useBtwCommand());

    act(() => {
      useBtwState.getState().open('Test');
      useBtwState.getState().appendDelta('Response');
    });

    expect(result.current.answer).toBe('Response');
  });
});
