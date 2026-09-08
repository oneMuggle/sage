/**
 * Sage API - Session API
 */

import { invoke } from './desktopInvoke';
import type { Message, Session, SessionCompactResult, SessionExportResult } from './types';
import { ApiException, handleApiError, isValidSessionId, withRetry } from './utils';

export const sessionApi = {
  async create(title: string = '新对话'): Promise<Session> {
    // 标题原文直传: React 渲染层负责转义, 此处转义会让标题以 HTML 实体形式落库
    return withRetry(async () => {
      try {
        const session = await invoke<Session>('create_session', { title });
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
   * U4' (对标增强第五轮批次 A): 会话重命名。
   *
   * PATCH 幂等,走 withRetry;标题原文直传（对齐 #516 数据污染修正——
   * 渲染层由 React 转义,此处转义会让标题以 HTML 实体形式落库）。
   */
  async rename(sessionId: string, title: string): Promise<Session> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    return withRetry(async () => {
      try {
        return await invoke<Session>('session_update', { sessionId, title });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * M4: 从会话分叉。复制 atMessageId 及之前的消息（缺省全部）到新会话。
   *
   * U5': `options.beforeMessage` 切换为**开区间**——复制 atMessageId 之前
   * 的消息（不含本身）；编辑重发据此分叉出被编辑消息之前的前缀。
   *
   * 刻意**不走 withRetry**：fork 非幂等，重试会创建重复会话。
   */
  async fork(
    sessionId: string,
    atMessageId?: string,
    title?: string,
    options?: { beforeMessage?: boolean },
  ): Promise<Session> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    try {
      return await invoke<Session>('session_fork', {
        sessionId,
        atMessageId,
        title,
        beforeMessage: options?.beforeMessage,
      });
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

  // ===== U8 (批次 B): 会话级模型覆盖 (G5 收尾) =====

  /** 读取会话的模型覆盖;未设置返回 null(跟随全局)。 */
  async getModelOverride(sessionId: string): Promise<string | null> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    return withRetry(async () => {
      try {
        const resp = await invoke<SessionModelWire>('session_get_model', { sessionId });
        return resp.model ?? null;
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /** 设置会话模型覆盖;传空串清除,回到全局选择。返回生效值(清除后为 null)。 */
  async setModelOverride(sessionId: string, model: string): Promise<string | null> {
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    return withRetry(async () => {
      try {
        const resp = await invoke<SessionModelWire>('session_set_model', {
          sessionId,
          model,
        });
        return resp.model ?? null;
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};

/** U8: 后端 GET/PUT /sessions/{id}/model 的 wire 形状 */
interface SessionModelWire {
  session_id: string;
  model: string | null;
}

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
