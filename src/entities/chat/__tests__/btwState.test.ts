// src/entities/chat/__tests__/btwState.test.ts
import { describe, it, expect, beforeEach } from 'vitest';

import {
  buildBtwStateAuditJson,
  buildBtwStateAuditSnapshot,
  useBtwState,
} from '../btwState';

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

  it('exports btwState audit snapshot and JSON helpers', () => {
    expect(buildBtwStateAuditSnapshot()).toBe(
      'open:no|question:no|answerLen:0|loading:no|parentRunning:no|sources:0',
    );
    expect(
      buildBtwStateAuditSnapshot({
        isOpen: true,
        hasQuestion: true,
        answerLength: 18,
        isLoading: false,
        parentTaskRunning: true,
        sourceCount: 2,
      }),
    ).toBe('open:yes|question:yes|answerLen:18|loading:no|parentRunning:yes|sources:2');

    const parsed = JSON.parse(
      buildBtwStateAuditJson({
        isOpen: true,
        hasQuestion: true,
        isLoading: true,
      }),
    );
    expect(parsed).toEqual({
      isOpen: true,
      hasQuestion: true,
      answerLength: 0,
      isLoading: true,
      parentTaskRunning: false,
      sourceCount: 0,
      snapshot: 'open:yes|question:yes|answerLen:0|loading:yes|parentRunning:no|sources:0',
    });
  });
});
