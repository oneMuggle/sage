// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { gatewayApi } from '../../../shared/api/gatewayApi';
import { GatewayCard } from '../GatewayCard';

vi.mock('../../../shared/api/gatewayApi', () => ({
  gatewayApi: {
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
    status: vi.fn(),
    listBinds: vi.fn(),
    unbind: vi.fn(),
  },
}));

const mockedApi = vi.mocked(gatewayApi);

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.getConfig.mockResolvedValue({
    configured: true,
    enabled: true,
    source: 'settings',
    bot_token_masked: '****ABCD',
    allowed_chat_ids: ['42'],
  });
  mockedApi.status.mockResolvedValue({
    configured: true,
    running: true,
    bound_chats: 1,
    stats: { updates_seen: 5, messages_replied: 4, rejected: 0, errors: 0 },
  });
  mockedApi.listBinds.mockResolvedValue({
    binds: [{ chat_id: '42', session_id: 'sess-abc', created_at: 1 }],
  });
});

describe('GatewayCard', () => {
  it('renders masked token and binds', async () => {
    render(<GatewayCard />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('****ABCD')).toBeInTheDocument();
    });
    expect(screen.getByText(/chat 42 → session/)).toBeInTheDocument();
    expect(screen.getByText(/绑定 1 个会话/)).toBeInTheDocument();
  });

  it('saves via PUT with edited values', async () => {
    mockedApi.updateConfig.mockResolvedValue({
      saved: true,
      restart_required: true,
    });
    render(<GatewayCard />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('****ABCD')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText('123456:ABC-DEF...'), {
      target: { value: 'new-token' },
    });
    fireEvent.change(screen.getByPlaceholderText('123456789, 987654321'), {
      target: { value: '7' },
    });
    fireEvent.click(screen.getByText('保存'));

    await waitFor(() => {
      expect(mockedApi.updateConfig).toHaveBeenCalledTimes(1);
    });
    expect(mockedApi.updateConfig).toHaveBeenCalledWith({
      bot_token: 'new-token',
      allowed_chat_ids: ['7'],
      enabled: true,
    });
    await waitFor(() => {
      expect(screen.getByText(/重启 Sage 后端/)).toBeInTheDocument();
    });
  });

  it('unbinds a chat after click', async () => {
    mockedApi.unbind.mockResolvedValue({ chat_id: '42', unbound: true });
    render(<GatewayCard />);
    await waitFor(() => {
      expect(screen.getByTitle('解绑')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTitle('解绑'));
    await waitFor(() => {
      expect(mockedApi.unbind).toHaveBeenCalledWith('42');
    });
    expect(screen.queryByText(/chat 42 → session/)).not.toBeInTheDocument();
  });
});
