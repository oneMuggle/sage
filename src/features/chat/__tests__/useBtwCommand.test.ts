import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useBtwState } from '../../../entities/chat/btwState';
import { useBtwCommand } from '../useBtwCommand';
import { formatBtwCommandStateJson, formatBtwCommandStateSummary } from '../useBtwCommand';

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

  it('formats btw command state summary and JSON (Phase P109)', () => {
    expect(
      formatBtwCommandStateSummary({ isOpen: false, question: '', answer: '', isLoading: false }),
    ).toBe('closed');
    const active = { isOpen: true, question: 'Why?', answer: 'Because.', isLoading: false };
    expect(formatBtwCommandStateSummary(active)).toBe('open · idle · q=4c · a=8c');
    const parsed = JSON.parse(formatBtwCommandStateJson(active));
    expect(parsed).toEqual({
      isOpen: true,
      isLoading: false,
      question: 'Why?',
      answerLength: 8,
    });
  });
});
