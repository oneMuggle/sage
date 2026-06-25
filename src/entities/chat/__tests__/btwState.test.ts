// src/entities/chat/__tests__/btwState.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useBtwState } from '../btwState';

describe('useBtwState', () => {
  beforeEach(() => {
    useBtwState.setState({
      isOpen: false,
      question: '',
      answer: '',
      isLoading: false,
      parentTaskRunning: false,
    });
  });

  it('has correct initial state', () => {
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(false);
    expect(s.question).toBe('');
    expect(s.answer).toBe('');
    expect(s.isLoading).toBe(false);
    expect(s.parentTaskRunning).toBe(false);
  });

  it('open() sets isOpen=true, stores question, clears answer', () => {
    useBtwState.getState().open('什么是 useEffect?');
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(true);
    expect(s.question).toBe('什么是 useEffect?');
    expect(s.answer).toBe('');
  });

  it('close() resets to initial state', () => {
    useBtwState.getState().open('q');
    useBtwState.getState().setLoading(true);
    useBtwState.getState().appendDelta('partial');
    useBtwState.getState().close();
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(false);
    expect(s.question).toBe('');
    expect(s.answer).toBe('');
    expect(s.isLoading).toBe(false);
  });

  it('appendDelta appends to existing answer', () => {
    useBtwState.getState().appendDelta('hello');
    useBtwState.getState().appendDelta(' world');
    expect(useBtwState.getState().answer).toBe('hello world');
  });

  it('setLoading() toggles isLoading', () => {
    useBtwState.getState().setLoading(true);
    expect(useBtwState.getState().isLoading).toBe(true);
    useBtwState.getState().setLoading(false);
    expect(useBtwState.getState().isLoading).toBe(false);
  });

  it('open() while already open replaces question and clears answer (重定义 /btw 互斥)', () => {
    useBtwState.getState().open('first');
    useBtwState.getState().appendDelta('partial answer');
    useBtwState.getState().open('second');
    const s = useBtwState.getState();
    expect(s.question).toBe('second');
    expect(s.answer).toBe('');
    expect(s.isOpen).toBe(true);
  });
});
