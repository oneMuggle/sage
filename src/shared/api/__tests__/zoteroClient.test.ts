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
});
