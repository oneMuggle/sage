/**
 * r87: gatewayApi 单元测试——多平台网关配置/状态/绑定。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockBackendRequest = vi.fn();

vi.mock('../backendRequest', () => ({
  backendRequest: (...args: unknown[]) => mockBackendRequest(...args),
}));

import { gatewayApiFor, gatewayAllowedIds } from '../gatewayApi';

beforeEach(() => { mockBackendRequest.mockReset(); });

describe('gatewayApiFor', () => {
  it('getConfig() sends GET to correct path', async () => {
    const config = { configured: true, enabled: true, source: 'settings', bot_token_masked: '***' };
    mockBackendRequest.mockResolvedValueOnce(config);
    const api = gatewayApiFor('telegram');
    const r = await api.getConfig();
    expect(mockBackendRequest).toHaveBeenCalledWith({ method: 'GET', path: expect.stringContaining('telegram') });
    expect(r).toEqual(config);
  });

  it('updateConfig() sends PUT with payload', async () => {
    mockBackendRequest.mockResolvedValueOnce({ saved: true, restart_required: false });
    const api = gatewayApiFor('discord');
    const payload = { bot_token: 'tok', enabled: true };
    const r = await api.updateConfig(payload);
    expect(mockBackendRequest).toHaveBeenCalledWith(expect.objectContaining({ method: 'PUT', body: payload }));
    expect(r.saved).toBe(true);
  });

  it('status() returns gateway status', async () => {
    const status = { configured: true, running: true, platform: 'telegram' };
    mockBackendRequest.mockResolvedValueOnce(status);
    const api = gatewayApiFor('telegram');
    const r = await api.status();
    expect(r).toEqual(status);
  });

  it('unbind() sends DELETE with chatId', async () => {
    mockBackendRequest.mockResolvedValueOnce({ chat_id: '123', unbound: true });
    const api = gatewayApiFor('telegram');
    const r = await api.unbind('123');
    expect(mockBackendRequest).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE' }));
    expect(r.unbound).toBe(true);
  });
});

describe('gatewayAllowedIds', () => {
  it('extracts allowed_chat_ids from Telegram config', () => {
    expect(gatewayAllowedIds({ allowed_chat_ids: ['123'], configured: true, enabled: true, source: 'env', bot_token_masked: '***' } as never)).toEqual(['123']);
  });

  it('extracts allowed_channel_ids from Discord/Slack config', () => {
    expect(gatewayAllowedIds({ allowed_channel_ids: ['456'], configured: true, enabled: true, source: 'env', bot_token_masked: '***' } as never)).toEqual(['456']);
  });
});
