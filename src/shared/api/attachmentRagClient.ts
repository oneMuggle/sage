/**
 * IPC client for chat-attachment vector RAG (r59).
 *
 * Backend: backend/api/chat_attachment_routes.py (r58 endpoints), library
 * layer in backend/services/attachment_rag.py (r57).
 *
 * Embedding config is request-level (same contract as wiki ingest) — the
 * caller decides which embed endpoint to use. Search takes an already-
 * embedded query vector: the renderer (or a future producer slice) embeds
 * the query, the route itself never performs embedding network calls.
 *
 * All methods throw on IPC failure; callers surface errors inline.
 */
import { invoke } from './desktopInvoke';

export interface AttachmentEmbedConfig {
  base_url: string;
  api_key?: string;
  model: string;
  /** 向量维度（text-embedding-3-small 默认 1536） */
  dim: number;
}

export interface AttachmentIndexReport {
  media_id: string;
  page_path: string;
  /** 0 = 无可索引文本（如扫描版 pdf），未落盘 */
  chunks: number;
  dim: number;
}

export interface AttachmentSearchHit {
  page_path: string;
  chunk_index: number;
  content: string;
  /** 余弦相似度 */
  score: number;
}

export interface AttachmentSearchInput {
  query_vector: number[];
  dim: number;
  /** 限定检索范围；缺省 = 全部已索引附件 */
  media_ids?: string[];
  limit?: number;
}

export const attachmentRagClient = {
  /** 为文档附件建立向量索引（显式触发；重复索引幂等替换）。 */
  async indexAttachment(
    mediaId: string,
    embed: AttachmentEmbedConfig,
    targetChunkSize?: number,
  ): Promise<AttachmentIndexReport> {
    return invoke('attachment_rag_index', {
      mediaId,
      embed,
      ...(targetChunkSize !== undefined ? { target_chunk_size: targetChunkSize } : {}),
    });
  },

  async searchAttachments(input: AttachmentSearchInput): Promise<AttachmentSearchHit[]> {
    const resp = await invoke<{ hits: AttachmentSearchHit[] }>('attachment_rag_search', {
      query_vector: input.query_vector,
      dim: input.dim,
      ...(input.media_ids ? { media_ids: input.media_ids } : {}),
      ...(input.limit !== undefined ? { limit: input.limit } : {}),
    });
    return resp.hits;
  },

  /** 删除附件索引（幂等：未索引 → removed=0）。 */
  async deleteAttachmentIndex(mediaId: string): Promise<{ media_id: string; removed: number }> {
    return invoke('attachment_rag_delete_index', { mediaId });
  },
};
