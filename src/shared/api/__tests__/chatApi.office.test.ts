/**
 * chatApi — Task 7 (2026-07-26) RED tests for the optional 5th arg
 * `officeRefs` in `chatStream`. Validates:
 *   - 5th arg forwarded verbatim into the `agent_chat_stream` invoke body
 *   - omitting the 5th arg yields `officeRefs: []` in the wire payload
 *   - existing callers without the 5th arg keep working unchanged
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();
const mockListen = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../desktopEvent', () => ({
  listen: (...args: unknown[]) => mockListen(...args),
}));

import { chatApi } from '../chatApi';
import type { ChatOfficeRef } from '../types';

function ref(docId: string, docType: ChatOfficeRef['docType'], filename: string): ChatOfficeRef {
  return { docId, docType, filename };
}

const SESSION_ID = '12345678-1234-1234-1234-1234567890ab';
const MESSAGE = 'hello world';
const BASE_HANDLERS = {
  onEvent: vi.fn(),
  onError: vi.fn(),
  onDone: vi.fn(),
};

beforeEach(() => {
  mockInvoke.mockReset();
  mockListen.mockReset();
  mockInvoke.mockResolvedValue({ streamId: 'stream-1' });
  mockListen.mockResolvedValue(() => undefined);
});

describe('chatApi.chatStream — officeRefs (Task 7)', () => {
  it('forwards the 5th arg officeRefs verbatim into the invoke body', async () => {
    const officeRefs: ChatOfficeRef[] = [
      ref('doc-1', 'ppt', 'a.pptx'),
      ref('doc-2', 'word', 'b.docx'),
    ];
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, undefined, officeRefs);
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ officeRefs }),
    );
  });

  it('serialises officeRefs as an empty array when omitted (4-arg callers)', async () => {
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS);
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ officeRefs: [] }),
    );
  });

  it('passes undefined officeRefs explicitly as an empty array', async () => {
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, undefined, undefined);
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ officeRefs: [] }),
    );
  });

  it('returns a streamId + cancel handle even when officeRefs are supplied', async () => {
    const officeRefs = [ref('doc-1', 'excel', 'a.xlsx')];
    const { streamId } = await chatApi.chatStream(
      SESSION_ID,
      MESSAGE,
      BASE_HANDLERS,
      undefined,
      officeRefs,
    );
    expect(streamId).toBe('stream-1');
  });

  it('does not mutate the call-supplied officeRefs array', async () => {
    const officeRefs = [ref('doc-1', 'ppt', 'a.pptx')];
    const before = officeRefs.length;
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, undefined, officeRefs);
    expect(officeRefs.length).toBe(before);
  });

  it('keeps config keys (apiKey/apiUrl/etc.) untouched when adding officeRefs', async () => {
    const officeRefs = [ref('doc-1', 'ppt', 'a.pptx')];
    const config = { apiKey: 'k', apiUrl: 'u', model: 'm' };
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, config, officeRefs);
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({
        apiKey: 'k',
        apiUrl: 'u',
        model: 'm',
        officeRefs,
      }),
    );
  });
});
