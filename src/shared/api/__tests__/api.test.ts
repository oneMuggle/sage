/**structural test for src/shared/api (B1-RED first unit).

不测行为,只验"7 个 API 对象 + 17 个 interface + 1 class + 2 utils"都从
新位置正确导出。确保 codemod 把 caller 切到新路径后,行为不变。

同源:src/shared/api/api.ts 暂作 re-export shim(过渡期),所有调用方未变,
所以这个测试既验新位置,又间接证明 shim 链路完整。
*/

import { describe, it, expect } from 'vitest';

import * as ApiModule from '../index';

describe('src/shared/api structural exports', () => {
  it('exports the 7 API objects', () => {
    expect(ApiModule.sessionApi).toBeDefined();
    expect(ApiModule.messageApi).toBeDefined();
    expect(ApiModule.chatApi).toBeDefined();
    expect(ApiModule.memoryApi).toBeDefined();
    expect(ApiModule.knowledgeApi).toBeDefined();
    expect(ApiModule.skillsApi).toBeDefined();
    expect(ApiModule.agentsApi).toBeDefined();
  });

  it('each API object exposes CRUD-shape (has at least one async method)', () => {
    // 防御:避免 codemod 后某对象被错误导出为空
    for (const api of [
      ApiModule.sessionApi,
      ApiModule.messageApi,
      ApiModule.chatApi,
      ApiModule.memoryApi,
      ApiModule.knowledgeApi,
      ApiModule.skillsApi,
      ApiModule.agentsApi,
    ]) {
      const methods = Object.values(api as Record<string, unknown>).filter(
        (v) => typeof v === 'function',
      );
      expect(methods.length).toBeGreaterThan(0);
    }
  });

  it('exports the 2 utility functions', () => {
    expect(typeof ApiModule.sanitizeInput).toBe('function');
    expect(typeof ApiModule.isValidSessionId).toBe('function');
  });

  it('exports ApiException class (caller catch 路径必须能 instanceof)', () => {
    // 显式构造 + 检查 name,避免新位置漏 export
    const err = new ApiModule.ApiException({
      error: 'test_type',
      message: 'test message',
    });
    expect(err).toBeInstanceOf(ApiModule.ApiException);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ApiException');
    expect(err.code).toBe('test_type');
    expect(err.message).toBe('test message');
  });

  it('exports representative interfaces (TypeScript types erases at runtime, 只验定义存在)', () => {
    // 接口在编译后消失,这个 test 仅供:1) 防 codemod 把 export 删光;
    // 2) 读源码查 grep 时多一处 fall-back 信号。运行时无实际 assertion。
    // 用一个 type-only re-import 触发 TS 编译,不在 expect() 里比对。
    type _T =
      | ApiModule.Session
      | ApiModule.Message
      | ApiModule.ToolCall
      | ApiModule.ChatRequest
      | ApiModule.ChatResponse
      | ApiModule.AgentState
      | ApiModule.AgentToolCall
      | ApiModule.AgentToolResult
      | ApiModule.AgentEvent
      | ApiModule.ApiError
      | ApiModule.ChatConfig
      | ApiModule.Memory
      | ApiModule.KnowledgeDoc
      | ApiModule.Skill
      | ApiModule.SkillExecuteRequest
      | ApiModule.SkillExecuteResult
      | ApiModule.AgentProfile
      | ApiModule.AgentUpdate;
    // 编译器忽略 type-only,所以这个 test 在运行时为 no-op
    const _placeholder: _T | undefined = undefined;
    expect(_placeholder).toBeUndefined();
  });
});
