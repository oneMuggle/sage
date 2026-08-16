/**
 * Sage API - Session API
 */

import { invoke } from './desktopInvoke';
import type { Message, Session, SessionCompactResult, SessionExportResult } from './types';
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

  /**
   * M4: 压缩会话上下文。
   *
   * 刻意**不走 withRetry**：失败路径（502）意味着 LLM 摘要出错，
   * 重试只会浪费 token；低于地板时后端返回 ok=true/compacted=false。
   */
  async compact(sessionId: string): Promise<SessionCompactResult> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    try {
      return await invoke<SessionCompactResult>('session_compact', { sessionId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * M4: 从会话分叉。复制 atMessageId 及之前的消息（缺省全部）到新会话。
   *
   * 刻意**不走 withRetry**：fork 非幂等，重试会创建重复会话。
   */
  async fork(sessionId: string, atMessageId?: string, title?: string): Promise<Session> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    try {
      return await invoke<Session>('session_fork', { sessionId, atMessageId, title });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * U18: 导出会话为自包含 HTML。
   *
   * 后端返回 JSON 信封 {html, filename}；调用方用 downloadHtmlFile()
   * 触发浏览器下载。导出是只读操作，幂等，走 withRetry。
   */
  async exportHtml(
    sessionId: string,
    theme: 'auto' | 'dark' | 'light' = 'auto',
  ): Promise<SessionExportResult> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    return withRetry(async () => {
      try {
        return await invoke<SessionExportResult>('export_session_html', { sessionId, theme });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};

/**
 * U18: 把导出 HTML 文本作为文件下载（Blob + 临时 <a download>）。
 *
 * Electron 渲染进程里 blob: URL 下载走 session 的 will-download 流程，
 * 弹出系统保存对话框；纯浏览器环境直接进下载目录。
 */
export function downloadHtmlFile(html: string, filename: string): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
