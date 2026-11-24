/**
 * MinerU 服务 API（后端 backend/api/mineru_routes.py → /api/v1/mineru/*）
 * 状态接口只返回 hasApiKey 布尔值，密钥不会出现在响应中。
 */

import { backendRequest } from './backendRequest';

export interface MineruStatus {
  configured: boolean;
  enabled: boolean;
  hasApiKey: boolean;
  reachable: boolean;
  serverAuthMode: 'bearer' | 'anonymous' | 'required' | 'unknown';
  serverTiers: string[] | null;
  serverVersion: string | null;
  reason: string;
}

export const mineruApi = {
  status(): Promise<MineruStatus> {
    return backendRequest<MineruStatus>({
      method: 'GET',
      path: '/api/v1/mineru/status',
    });
  },
};
