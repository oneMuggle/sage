/** 网关 API（Round 20 Telegram / Round 16b Discord·Slack 多平台）。路由挂载于 /api/v1。 */

import { backendRequest } from './backendRequest';

export type GatewayPlatform = 'telegram' | 'discord' | 'slack';

/** 平台路径段（REST 资源名） */
export const GATEWAY_PLATFORMS: GatewayPlatform[] = ['telegram', 'discord', 'slack'];

export const gatewayPlatformLabel: Record<GatewayPlatform, string> = {
  telegram: 'Telegram',
  discord: 'Discord',
  slack: 'Slack',
};

interface GatewayConfigViewBase {
  configured: boolean;
  enabled: boolean;
  source: 'env' | 'settings' | 'none';
  bot_token_masked: string;
}

export interface TelegramGatewayConfigView extends GatewayConfigViewBase {
  allowed_chat_ids: string[];
}

/** Discord / Slack 白名单是 channel 粒度（Round 16） */
export interface ChannelGatewayConfigView extends GatewayConfigViewBase {
  allowed_channel_ids: string[];
}

export type GatewayConfigView = TelegramGatewayConfigView | ChannelGatewayConfigView;

export function gatewayAllowedIds(config: GatewayConfigView): string[] {
  if ('allowed_chat_ids' in config) return config.allowed_chat_ids;
  return config.allowed_channel_ids;
}

export interface GatewayStatus {
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

export interface GatewayBind {
  chat_id: string;
  session_id: string;
  created_at: number;
}

export interface GatewayUpdatePayload {
  bot_token: string;
  allowed_chat_ids?: string[];
  allowed_channel_ids?: string[];
  enabled: boolean;
}

const path = (platform: GatewayPlatform, resource: string) =>
  `/api/v1/gateway/${platform}/${resource}`;

export const gatewayApiFor = (platform: GatewayPlatform) => ({
  async getConfig(): Promise<GatewayConfigView> {
    return backendRequest<GatewayConfigView>({ method: 'GET', path: path(platform, 'config') });
  },

  async updateConfig(payload: GatewayUpdatePayload): Promise<{
    saved: boolean;
    restart_required: boolean;
  }> {
    return backendRequest({ method: 'PUT', path: path(platform, 'config'), body: payload });
  },

  async status(): Promise<GatewayStatus> {
    return backendRequest<GatewayStatus>({ method: 'GET', path: path(platform, 'status') });
  },

  async listBinds(): Promise<{ binds: GatewayBind[] }> {
    return backendRequest<{ binds: GatewayBind[] }>({
      method: 'GET',
      path: path(platform, 'binds'),
    });
  },

  async unbind(chatId: string): Promise<{ chat_id: string; unbound: boolean }> {
    return backendRequest({
      method: 'DELETE',
      path: `${path(platform, 'binds')}/${encodeURIComponent(chatId)}`,
    });
  },
});

/** 旧入口：Telegram 网关（Round 20 契约，兼容保留） */
export const gatewayApi = gatewayApiFor('telegram');
