// R106 会话级规则 IPC 路由合约：sessionId 只进路径（url-encode），
// delete 的 body 只留 tool_pattern/decision（后端
// PermissionRuleDeleteBody 是 extra="forbid"），clear 无内容体。
// 独立成文件避免 commands.test.ts 的 architecture 基线继续增长。
import { describe, expect, it } from 'vitest';

import { COMMAND_ROUTES } from '../commands';

describe('session remembered-rules IPC routes (R106)', () => {
  it('has permissions_list_session_rules route: GET with url-encoded sessionId', () => {
    const r = COMMAND_ROUTES.permissions_list_session_rules;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({ sessionId: 's-1' })).toBe('/api/v1/permissions/session/s-1/remembered-rules');
    expect(r.path({ sessionId: 'id/with slash' })).toBe(
      '/api/v1/permissions/session/id%2Fwith%20slash/remembered-rules',
    );
    expect(r.body).toBeUndefined();
  });

  it('permissions_delete_session_rule strips sessionId from the body', () => {
    const r = COMMAND_ROUTES.permissions_delete_session_rule;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({ sessionId: 's-1' })).toBe(
      '/api/v1/permissions/session/s-1/remembered-rules/delete',
    );
    expect(
      r.body!({
        sessionId: 's-1',
        toolPattern: 'bash',
        decision: 'allow',
        extraField: 'x',
      }),
    ).toEqual({ tool_pattern: 'bash', decision: 'allow' });
  });

  it('permissions_clear_session_rules posts an empty body to the session path', () => {
    const r = COMMAND_ROUTES.permissions_clear_session_rules;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({ sessionId: 's-1' })).toBe(
      '/api/v1/permissions/session/s-1/remembered-rules/clear',
    );
    expect(r.body!({ sessionId: 's-1', toolPattern: '*' })).toEqual({});
  });
});
