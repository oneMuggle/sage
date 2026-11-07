import { beforeEach, describe, expect, it, vi } from 'vitest';

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock('../desktopInvoke', () => ({ invoke }));

import { aiApi } from '../aiApi';

describe('aiApi', () => {
  beforeEach(() => invoke.mockReset());

  it('maps rewrite args to the IPC command', async () => {
    invoke.mockResolvedValue({ ok: true, result: 'r', model: 'm' });

    const result = await aiApi.rewrite({
      workspacePath: '/ws',
      documentId: 'doc-1',
      text: 'src',
      instruction: 'polish',
      targetLang: 'en',
    });

    expect(invoke).toHaveBeenCalledWith('office_ai_rewrite', {
      workspacePath: '/ws',
      documentId: 'doc-1',
      text: 'src',
      instruction: 'polish',
      targetLang: 'en',
    });
    expect(result.result).toBe('r');
  });

  it('maps chat args including history', async () => {
    invoke.mockResolvedValue({ ok: true, reply: 'a', model: null });

    await aiApi.chat({
      workspacePath: '/ws',
      documentId: 'doc-1',
      message: 'q',
      history: [{ role: 'user', content: 'hi' }],
      documentContext: 'ctx',
    });

    expect(invoke).toHaveBeenCalledWith('office_ai_chat', {
      workspacePath: '/ws',
      documentId: 'doc-1',
      message: 'q',
      history: [{ role: 'user', content: 'hi' }],
      documentContext: 'ctx',
    });
  });
});
