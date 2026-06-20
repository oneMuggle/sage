/**
 * Sage API - Session API
 */

import { invoke } from './desktopInvoke';
import type { Message, Session } from './types';
import { ApiException, handleApiError, isValidSessionId, sanitizeInput, withRetry } from './utils';

export const sessionApi = {
  async create(title: string = '新对话'): Promise<Session> {
    // 安全化标题输入
    const safeTitle = sanitizeInput(title);

    return withRetry(async () => {
      try {
        const session = await invoke<Session>('create_session', { title: safeTitle });
        return session;
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async list(): Promise<Session[]> {
    return withRetry(async () => {
      try {
        return await invoke<Session[]>('list_sessions');
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async get(id: string): Promise<Session> {
    // 验证会话ID
    if (!isValidSessionId(id)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId: id },
      });
    }

    return withRetry(async () => {
      try {
        return await invoke<Session>('get_session', { id });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async delete(id: string): Promise<void> {
    // 验证会话ID
    if (!isValidSessionId(id)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId: id },
      });
    }

    return withRetry(async () => {
      try {
        await invoke('delete_session', { id });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async getMessages(sessionId: string): Promise<Message[]> {
    // 验证会话ID
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }

    return withRetry(async () => {
      try {
        return await invoke<Message[]>('get_messages', { sessionId });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
