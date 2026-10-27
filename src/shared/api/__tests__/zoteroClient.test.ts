/**
 * r94: zoteroClient 单元测试——6 方法的通道约定与载荷归一化。
 *
 * 该 client 不经 handleApiError 包装（IPC 失败原样抛出），与 attachmentRagClient 同契约。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { zoteroClient } from '../zoteroClient';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('zoteroClient', () => {
  it('status() 空载荷调用 zotero_status', async () => {
    const status = { available: true, db_path: 'C:/zotero.sqlite', error: null, stats: { items: 1, collections: 2, tags: 3, attachments: 4 } };
    mockInvoke.mockResolvedValueOnce(status);
    const r = await zoteroClient.status();
    expect(mockInvoke).toHaveBeenCalledWith('zotero_status', {});
    expect(r.available).toBe(true);
  });

  it('search() 参数原样透传', async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await zoteroClient.search({ q: 'hunter', collection_key: 'CK1', tag: 'ml', limit: 5 });
    expect(mockInvoke).toHaveBeenCalledWith('zotero_search', {
      q: 'hunter', collection_key: 'CK1', tag: 'ml', limit: 5,
    });
  });

  it('getItem() 传 item_key', async () => {
    mockInvoke.mockResolvedValueOnce({ key: 'ITEM1', title: 't' });
    await zoteroClient.getItem('ITEM1');
    expect(mockInvoke).toHaveBeenCalledWith('zotero_item', { item_key: 'ITEM1' });
  });

  it('getAnnotations() 传 item_key', async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await zoteroClient.getAnnotations('ITEM2');
    expect(mockInvoke).toHaveBeenCalledWith('zotero_annotations', { item_key: 'ITEM2' });
  });

  it('listCollections() 无参时 parent_key 归一化为 null', async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await zoteroClient.listCollections();
    expect(mockInvoke).toHaveBeenCalledWith('zotero_collections', { parent_key: null });
  });

  it('listCollections() 显式 parent_key 透传', async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await zoteroClient.listCollections('PARENT1');
    expect(mockInvoke).toHaveBeenCalledWith('zotero_collections', { parent_key: 'PARENT1' });
  });

  it('setPath() 传 path', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, db_path: 'C:/new.sqlite' });
    const r = await zoteroClient.setPath('C:/new.sqlite');
    expect(mockInvoke).toHaveBeenCalledWith('zotero_set_path', { path: 'C:/new.sqlite' });
    expect(r.ok).toBe(true);
  });

  it('IPC 失败原样抛出（无 handleApiError 包装）', async () => {
    const raw = new Error('ipc dead');
    mockInvoke.mockRejectedValueOnce(raw);
    await expect(zoteroClient.status()).rejects.toBe(raw);
  });

  it('sync() 缺省 force=false、project_path=null', async () => {
    mockInvoke.mockResolvedValueOnce({
      items: 3, chunks: 3, dim: 1024, last_sync_ts: 'ts',
      skipped: false, elapsed_ms: 12, errors: [],
    });
    await zoteroClient.sync();
    expect(mockInvoke).toHaveBeenCalledWith('zotero_sync', {
      force: false, project_path: null,
    });
  });

  it('sync() 透传 force 与 projectPath', async () => {
    mockInvoke.mockResolvedValueOnce({
      items: 3, chunks: 3, dim: 1024, last_sync_ts: 'ts',
      skipped: false, elapsed_ms: 12, errors: [],
      wiki: { items_exported: 1, authors_exported: 2, errors: [] },
    });
    const r = await zoteroClient.sync({ force: true, projectPath: '/tmp/proj' });
    expect(mockInvoke).toHaveBeenCalledWith('zotero_sync', {
      force: true, project_path: '/tmp/proj',
    });
    expect(r.wiki?.items_exported).toBe(1);
  });

  it('syncStatus() 空载荷调用 zotero_sync_status', async () => {
    mockInvoke.mockResolvedValueOnce({
      last_sync_ts: null, last_sync_at: null, item_count: 0, wiki_page_count: 0,
      embedding_configured: false, vector_dim: null, sync_in_progress: false, errors: [],
    });
    const r = await zoteroClient.syncStatus();
    expect(mockInvoke).toHaveBeenCalledWith('zotero_sync_status', {});
    expect(r.embedding_configured).toBe(false);
  });

  it('getWikiTag() 读取 preferences KV，空值回退默认', async () => {
    mockInvoke.mockResolvedValueOnce({ value: null });
    await expect(zoteroClient.getWikiTag()).resolves.toBe('sage:wiki');
    expect(mockInvoke).toHaveBeenCalledWith('get_preference', { key: 'zotero_wiki_tag' });
  });

  it('getWikiTag() 返回已配置值', async () => {
    mockInvoke.mockResolvedValueOnce({ value: 'custom:tag' });
    await expect(zoteroClient.getWikiTag()).resolves.toBe('custom:tag');
  });

  it('setWikiTag() 写入 preferences KV，空串回退默认', async () => {
    mockInvoke.mockResolvedValueOnce(null);
    await zoteroClient.setWikiTag('   ');
    expect(mockInvoke).toHaveBeenCalledWith('set_preference', {
      key: 'zotero_wiki_tag', value: 'sage:wiki', value_type: 'string', category: 'general',
    });
  });

  it('setWikiTag() 保存去空格后的标签', async () => {
    mockInvoke.mockResolvedValueOnce(null);
    await zoteroClient.setWikiTag('  mine:wiki  ');
    expect(mockInvoke).toHaveBeenCalledWith('set_preference', {
      key: 'zotero_wiki_tag', value: 'mine:wiki', value_type: 'string', category: 'general',
    });
  });
});
