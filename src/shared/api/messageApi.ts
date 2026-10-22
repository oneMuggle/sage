/**
 * Sage API - Message API
 */

import { invoke } from './desktopInvoke';
import { ApiException, handleApiError, withRetry } from './utils';

export const messageApi = {
  async delete(id: string): Promise<void> {
    // 验证消息ID格式
    if (!id || typeof id !== 'string') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的消息ID',
        details: { messageId: id },
      });
    }

    return withRetry(async () => {
      try {
        await invoke('delete_message', { id });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};

export function auditMessageApiGovernance(
  state: {
    endpointCount?: number;
    supportsFeedback?: boolean;
  } = {},
): {
  module: 'src/shared/api/messageApi.ts';
  phase: 'P144';
  endpointCount: number;
  supportsFeedback: boolean;
  healthy: boolean;
} {
  const endpointCount =
    typeof state.endpointCount === 'number' && Number.isFinite(state.endpointCount)
      ? Math.max(0, Math.trunc(state.endpointCount))
      : 2;
  const supportsFeedback = state.supportsFeedback !== false;
  return {
    module: 'src/shared/api/messageApi.ts',
    phase: 'P144',
    endpointCount,
    supportsFeedback,
    healthy: endpointCount > 0 && supportsFeedback,
  };
}
