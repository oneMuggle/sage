// src/entities/routing/__tests__/taskType.test.ts
// Task 7 (2026-10-28): 智能路由任务类型的枚举与 localStorage 持久化。
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_ROUTING_TASK_TYPE,
  ROUTING_TASK_TYPES,
  ROUTING_TASK_TYPE_STORAGE_KEY,
  getRoutingTaskType,
  setRoutingTaskType,
} from '../taskType';

describe('routing taskType persistence', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('defaults to chat when nothing is stored', () => {
    expect(getRoutingTaskType()).toBe('chat');
    expect(DEFAULT_ROUTING_TASK_TYPE).toBe('chat');
  });

  it('round-trips a stored task type', () => {
    setRoutingTaskType('code_review');

    expect(localStorage.getItem(ROUTING_TASK_TYPE_STORAGE_KEY)).toBe('code_review');
    expect(getRoutingTaskType()).toBe('code_review');
  });

  it('falls back to the default for an unknown stored value', () => {
    localStorage.setItem(ROUTING_TASK_TYPE_STORAGE_KEY, 'runtime_classifier');

    expect(getRoutingTaskType()).toBe('chat');
  });

  it('falls back to the default when localStorage.getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage denied');
    });

    expect(getRoutingTaskType()).toBe('chat');
  });

  it('swallows localStorage.setItem failures', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });

    expect(() => setRoutingTaskType('analysis')).not.toThrow();
  });

  it('exposes every backend task type exactly once', () => {
    const expected = [
      'simple_chat',
      'chat',
      'code_generation',
      'code_review',
      'analysis',
      'writing',
      'translation',
      'summarization',
      'vision_task',
    ];

    expect([...ROUTING_TASK_TYPES].sort()).toEqual(expected.sort());
  });
});
