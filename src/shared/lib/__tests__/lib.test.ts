/**structural test for src/shared/lib (B1-RED second unit: 4 files batch).

不测行为,只验 4 文件(errorMapping / logger / store / utils)都从
新位置正确导出。结构模仿 B1 第一个 unit(src/shared/api/__tests__/api.test.ts)。

4 个 __tests__/ 旧测试(在 src/lib/__tests__/)仍走 shim 路径,本测试
只关注新位置的 export 形状,确保 codemod 后行为不变。
*/

import { describe, it, expect } from 'vitest';

import * as ErrorMapping from '../errorMapping';
import * as Logger from '../logger';
import * as Store from '../store';
import * as Utils from '../utils';

describe('src/shared/lib/errorMapping', () => {
  it('exports mapLLMErrorToText function (7 个 LLMErrorTypeFE 类型 → 7 个中文 hint)', () => {
    expect(typeof ErrorMapping.mapLLMErrorToText).toBe('function');
    // 烟雾:7 个类型都应映射(函数接 LLMErrorResponse 对象,不是 string)
    for (const t of [
      'auth_failed',
      'rate_limited',
      'server_error',
      'network_error',
      'timeout',
      'parsing_error',
      'unknown',
    ] as const) {
      const result = ErrorMapping.mapLLMErrorToText({
        type: t,
        message: 'x',
        status_code: null,
        retry_after: null,
      });
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    }
  });
});

describe('src/shared/lib/logger', () => {
  it('exports logger singleton instance (named export, not default)', () => {
    expect(Logger.logger).toBeDefined();
  });

  it('logger instance has 4 standard methods (debug/info/warn/error)', () => {
    const l = Logger.logger;
    expect(typeof l.debug).toBe('function');
    expect(typeof l.info).toBe('function');
    expect(typeof l.warn).toBe('function');
    expect(typeof l.error).toBe('function');
  });
});

describe('src/shared/lib/store', () => {
  it('exports useStore hook (zustand)', () => {
    expect(typeof Store.useStore).toBe('function');
  });

  it('exports 4 API re-exports (sessionApi / messageApi / chatApi / memoryApi)', () => {
    expect(Store.sessionApi).toBeDefined();
    expect(Store.messageApi).toBeDefined();
    expect(Store.chatApi).toBeDefined();
    expect(Store.memoryApi).toBeDefined();
  });

  it('exports 5 Lazy* page import functions', () => {
    expect(typeof Store.LazyChat).toBe('function');
    expect(typeof Store.LazySettings).toBe('function');
    expect(typeof Store.LazyMemory).toBe('function');
    expect(typeof Store.LazySkills).toBe('function');
    expect(typeof Store.LazyKnowledge).toBe('function');
  });

  it('exports 3 cache helper functions (getCachedMessages / setCachedMessages / clearCachedMessages)', () => {
    expect(typeof Store.getCachedMessages).toBe('function');
    expect(typeof Store.setCachedMessages).toBe('function');
    expect(typeof Store.clearCachedMessages).toBe('function');
  });

  it('exports representative types (TS 编译时 erases, type-only placeholder)', () => {
    // 接口在运行时消失,只验 type-level 编译可过。
    type _T = Store.Session | Store.Message | Store.ToolCall;
    const _placeholder: _T | undefined = undefined;
    expect(_placeholder).toBeUndefined();
  });
});

describe('src/shared/lib/utils', () => {
  it('exports 5 utility functions (formatDate, formatRelativeTime, generateId, truncate, copyToClipboard)', () => {
    expect(typeof Utils.formatDate).toBe('function');
    expect(typeof Utils.formatRelativeTime).toBe('function');
    expect(typeof Utils.generateId).toBe('function');
    expect(typeof Utils.truncate).toBe('function');
    expect(typeof Utils.copyToClipboard).toBe('function');
  });
});
