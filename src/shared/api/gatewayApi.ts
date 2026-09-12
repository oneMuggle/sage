/** Telegram 网关 API（Round 20: 前端设置卡）。路由挂载于 /api/v1。 */

import { backendRequest } from './backendRequest';

export interface TelegramGatewayConfigView {
  configured: boolean;
  enabled: boolean;
  source: 'env' | 'settings' | 'none';
  bot_token_masked: string;
  allowed_chat_ids: string[];
}

export interface TelegramGatewayStatus {
  configured: boolean;
  running: boolean;
  bound_chats: number;
  stats: {
    updates_seen: number;
    messages_replied: number;
    rejected: number;
    errors: number;
  };
}

export interface TelegramGatewayBind {
  chat_id: string;
  session_id: string;
  created_at: number;
}

export interface TelegramGatewayUpdatePayload {
  bot_token: string;
  allowed_chat_ids: string[];
  enabled: boolean;
}

export const gatewayApi = {
  async getConfig(): Promise<TelegramGatewayConfigView> {
    return backendRequest<TelegramGatewayConfigView>({
      method: 'GET',
      path: '/api/v1/gateway/telegram/config',
    });
  },

  async updateConfig(payload: TelegramGatewayUpdatePayload): Promise<{
    saved: boolean;
    restart_required: boolean;
  }> {
    return backendRequest({
      method: 'PUT',
      path: '/api/v1/gateway/telegram/config',
      body: payload,
    });
  },

  async status(): Promise<TelegramGatewayStatus> {
    return backendRequest<TelegramGatewayStatus>({
      method: 'GET',
      path: '/api/v1/gateway/telegram/status',
    });
  },

  async listBinds(): Promise<{ binds: TelegramGatewayBind[] }> {
    return backendRequest<{ binds: TelegramGatewayBind[] }>({
      method: 'GET',
      path: '/api/v1/gateway/telegram/binds',
    });
  },

  async unbind(chatId: string): Promise<{ chat_id: string; unbound: boolean }> {
    return backendRequest({
      method: 'DELETE',
      path: `/api/v1/gateway/telegram/binds/${encodeURIComponent(chatId)}`,
    });
  },
};
