/**
 * r93: attachmentRagClient 单元测试——索引/检索/删除的条件载荷约定。
 *
 * 该 client 不经 handleApiError 包装（IPC 失败原样抛出），错误路径断言原始传播。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { attachmentRagClient } from '../attachmentRagClient';

const EMBED = { base_url: 'https://emb.example/v1', api_key: 'k', model: 'm', dim: 4 };

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('attachmentRagClient', () => {
  it('indexAttachment() 传 mediaId + embed 配置', async () => {
    const report = { media_id: 'm1', page_path: 'p.md', chunks: 7, dim: 4 };
    mockInvoke.mockResolvedValueOnce(report);
    const r = await attachmentRagClient.indexAttachment('m1', EMBED);
    expect(mockInvoke).toHaveBeenCalledWith('attachment_rag_index', { mediaId: 'm1', embed: EMBED });
    expect(mockInvoke.mock.calls[0][1].target_chunk_size).toBeUndefined();
    expect(r.chunks).toBe(7);
  });

  it('indexAttachment() 可带 target_chunk_size', async () => {
    mockInvoke.mockResolvedValueOnce({ media_id: 'm1', page_path: 'p', chunks: 0, dim: 4 });
    await attachmentRagClient.indexAttachment('m1', EMBED, 512);
    const payload = mockInvoke.mock.calls[0][1];
    expect(payload.target_chunk_size).toBe(512);
  });

  it('searchAttachments() 缺省省略 media_ids/limit', async () => {
    const hits = [{ page_path: 'p.md', chunk_index: 0, content: 'c', score: 0.9 }];
    mockInvoke.mockResolvedValueOnce({ hits });
    const r = await attachmentRagClient.searchAttachments({ query_vector: [1, 2], dim: 2 });
    expect(mockInvoke).toHaveBeenCalledWith('attachment_rag_search', {
      query_vector: [1, 2],
      dim: 2,
    });
    expect(r).toEqual(hits);
  });

  it('searchAttachments() 显式 media_ids 与 limit', async () => {
    mockInvoke.mockResolvedValueOnce({ hits: [] });
    await attachmentRagClient.searchAttachments({
      query_vector: [0.5],
      dim: 1,
      media_ids: ['a', 'b'],
      limit: 5,
    });
    expect(mockInvoke).toHaveBeenCalledWith('attachment_rag_search', {
      query_vector: [0.5],
      dim: 1,
      media_ids: ['a', 'b'],
      limit: 5,
    });
  });

  it('deleteAttachmentIndex() 传 mediaId，幂等返回 removed', async () => {
    mockInvoke.mockResolvedValueOnce({ media_id: 'm1', removed: 0 });
    const r = await attachmentRagClient.deleteAttachmentIndex('m1');
    expect(mockInvoke).toHaveBeenCalledWith('attachment_rag_delete_index', { mediaId: 'm1' });
    expect(r.removed).toBe(0);
  });

  it('IPC 失败原样抛出（无 handleApiError 包装）', async () => {
    const raw = new Error('ipc dead');
    mockInvoke.mockRejectedValueOnce(raw);
    await expect(attachmentRagClient.deleteAttachmentIndex('m1')).rejects.toBe(raw);
  });
});
