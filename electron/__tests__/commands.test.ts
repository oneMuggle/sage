import { describe, expect, it } from 'vitest';
import { COMMAND_ROUTES, UnknownIpcCommandError } from '../commands';

describe('COMMAND_ROUTES', () => {
  it('includes the full session/message/chat surface used by the renderer', () => {
    const required = [
      'agent_chat_stream',
      'attach_chat_stream',
      'interrupt_agent',
      'list_sessions',
      'create_session',
      'delete_session',
      'get_messages',
      'delete_message',
    ];
    for (const cmd of required) {
      expect(COMMAND_ROUTES[cmd], `missing route for ${cmd}`).toBeDefined();
    }
  });

  // I2: agent_chat_stream 改为同步 create(JSON 立即返回 streamId),不再是 SSE
  it('agent_chat_stream is now plain POST /chat/stream (not SSE)', () => {
    const r = COMMAND_ROUTES.agent_chat_stream;
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/chat/stream');
    expect(r.isSse).toBeUndefined();
  });

  it('attach_chat_stream is GET with streamId as path param (url-encoded)', () => {
    const r = COMMAND_ROUTES.attach_chat_stream;
    expect(r.method).toBe('GET');
    expect(r.path({ streamId: 'sid/1' })).toBe('/chat/stream/sid%2F1');
    expect(r.path({ streamId: 'abc-123' })).toBe('/chat/stream/abc-123');
  });

  it('builds list_sessions URL with limit/offset query params', () => {
    const path = COMMAND_ROUTES.list_sessions.path({ limit: 50, offset: 10 });
    expect(path).toBe('/sessions?limit=50&offset=10');
  });

  it('defaults list_sessions limit/offset to 100/0', () => {
    expect(COMMAND_ROUTES.list_sessions.path({})).toBe('/sessions?limit=100&offset=0');
  });

  it('builds get_messages URL with sessionId encoded', () => {
    const path = COMMAND_ROUTES.get_messages.path({ sessionId: 's/1' });
    expect(path).toBe('/sessions/s%2F1/messages?limit=100&offset=0');
  });

  it('builds create_session as POST /sessions', () => {
    expect(COMMAND_ROUTES.create_session.method).toBe('POST');
    expect(COMMAND_ROUTES.create_session.path({})).toBe('/sessions');
  });
});

describe('UnknownIpcCommandError', () => {
  it('names the offending command and references the source of truth', () => {
    const err = new UnknownIpcCommandError('foo_bar');
    expect(err.message).toMatch(/foo_bar/);
    expect(err.message).toMatch(/COMMAND_ROUTES/);
    expect(err.name).toBe('UnknownIpcCommandError');
  });
});
