// 对话阅读体验第二轮 C2：回答版本 —— 最后一轮判定、原位重新生成、后端接口封装。
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Message } from '../../../shared/lib/store';
import {
  activateAnswerVersion,
  fetchAnswerVersions,
  lastTurnAnchorIndex,
  regenerateInPlace,
} from '../answerVersions';

const backendRequest = vi.fn();
vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: (...args: unknown[]) => backendRequest(...args),
}));
let demoMode = false;
vi.mock('../../../shared/api/demoFlag', () => ({ isDemoMode: () => demoMode }));

const msg = (id: string, role: Message['role'], content = id): Message => ({
  id,
  session_id: 's1',
  role,
  content,
  created_at: 1,
});

const conversation: Message[] = [
  msg('u1', 'user', '一'),
  msg('a1', 'assistant'),
  msg('u2', 'user', '二'),
  msg('a2', 'assistant'),
  msg('a3', 'assistant'),
];

beforeEach(() => {
  backendRequest.mockReset();
  demoMode = false;
});

describe('lastTurnAnchorIndex', () => {
  it('finds the user message that opens the last turn', () => {
    expect(lastTurnAnchorIndex(conversation, 4)).toBe(2);
    expect(lastTurnAnchorIndex(conversation, 3)).toBe(2);
  });

  it('rejects earlier turns and answers without a question', () => {
    expect(lastTurnAnchorIndex(conversation, 1)).toBe(-1);
    expect(lastTurnAnchorIndex([msg('a0', 'assistant')], 0)).toBe(-1);
  });
});

describe('regenerateInPlace', () => {
  it('drops the old answer locally and resends the question with regenerateOf', () => {
    const removeMessage = vi.fn();
    const sendMessage = vi.fn().mockResolvedValue(undefined);

    expect(regenerateInPlace(conversation, 4, 's1', { removeMessage, sendMessage })).toBe(true);

    expect(removeMessage.mock.calls.map(([id]) => id)).toEqual(['a2', 'a3']);
    expect(sendMessage).toHaveBeenCalledWith('二', 's1', undefined, undefined, {
      regenerateOf: 'u2',
    });
  });

  it('leaves earlier turns and demo mode to the fork flow', () => {
    const deps = { removeMessage: vi.fn(), sendMessage: vi.fn() };
    expect(regenerateInPlace(conversation, 1, 's1', deps)).toBe(false);
    demoMode = true;
    expect(regenerateInPlace(conversation, 4, 's1', deps)).toBe(false);
    expect(deps.removeMessage).not.toHaveBeenCalled();
    expect(deps.sendMessage).not.toHaveBeenCalled();
  });
});

describe('answer version api', () => {
  it('lists and activates versions through the backend relay', async () => {
    backendRequest.mockResolvedValueOnce({
      anchor_id: 'u2',
      total: 2,
      current_index: 2,
      versions: [],
    });
    await expect(fetchAnswerVersions('s 1')).resolves.toMatchObject({ total: 2 });
    expect(backendRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/sessions/s%201/answer-versions',
      method: 'GET',
    });

    backendRequest.mockResolvedValueOnce({ ok: true, restored: 1 });
    await activateAnswerVersion('s1', 'ver-1');
    expect(backendRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/sessions/s1/answer-versions/ver-1/activate',
      method: 'POST',
    });
  });
});
