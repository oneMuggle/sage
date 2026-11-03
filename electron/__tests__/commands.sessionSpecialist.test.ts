/**
 * session_update 的 specialist_id 透传断言（M0 · 2026-11-03 会话级专家绑定）。
 *
 * 独立成文件而非塞进 commands.test.ts —— 后者有 architecture-baseline.json
 * 的行数基线（见 commands.sessionRules.test.ts 同款说明）。
 *
 * 语义要点：specialist_id 只影响本会话后续轮次的人设 / 工具白名单 / 模型 /
 * 记忆策略，不触碰历史消息；空串 = 解绑回主助手，必须显式下发。
 */
import { describe, expect, it } from 'vitest';

import { COMMAND_ROUTES } from '../commands';

describe('session specialist binding IPC route (M0)', () => {
  it('passes specialist_id through the session_update PATCH body', () => {
    expect(
      COMMAND_ROUTES.session_update.body?.({ sessionId: 's1', specialistId: 'writer' }),
    ).toEqual({ specialist_id: 'writer' });
  });

  it('keeps an empty specialist_id so unbinding reaches the backend', () => {
    expect(COMMAND_ROUTES.session_update.body?.({ sessionId: 's1', specialistId: '' })).toEqual({
      specialist_id: '',
    });
  });

  it('omits specialist_id when the caller did not pass one', () => {
    expect(COMMAND_ROUTES.session_update.body?.({ sessionId: 's1' })).toEqual({});
  });
});
