import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { themeCssClient } from '../themeCssClient';
import type { ThemeCssPayload } from '../../../features/theme/themeCssTypes';

const validPayload: ThemeCssPayload = {
  id: '550e8400-e29b-41d4-a716-446655440000',
  name: '测试主题',
  css: ':root { --bg: #000; }',
  cover: undefined,
  appearance: 'dark',
  created_at: 1700000000000,
  updated_at: 1700000001000,
};

describe('themeCssClient', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  // ─── save ──────────────────────────────────────────────

  describe('save', () => {
    it('成功时调用 theme_save 并返回 { id }', async () => {
      mockInvoke.mockResolvedValue({ id: validPayload.id });
      const result = await themeCssClient.save(validPayload);
      expect(result).toEqual({ id: validPayload.id });
      expect(mockInvoke).toHaveBeenCalledWith('theme_save', { payload: validPayload });
    });

    it('失败时抛出错误', async () => {
      mockInvoke.mockRejectedValue(new Error('save failed'));
      await expect(themeCssClient.save(validPayload)).rejects.toThrow('save failed');
    });
  });

  // ─── list ──────────────────────────────────────────────

  describe('list', () => {
    it('成功时返回经 zod 校验的数组', async () => {
      mockInvoke.mockResolvedValue([validPayload]);
      const result = await themeCssClient.list();
      expect(result).toEqual([validPayload]);
      expect(mockInvoke).toHaveBeenCalledWith('theme_list', {});
    });

    it('空列表返回空数组', async () => {
      mockInvoke.mockResolvedValue([]);
      const result = await themeCssClient.list();
      expect(result).toEqual([]);
    });

    it('IPC 失败时返回空数组（不抛）', async () => {
      mockInvoke.mockRejectedValue(new Error('IPC fail'));
      const result = await themeCssClient.list();
      expect(result).toEqual([]);
    });

    it('zod 校验失败时返回空数组（脏数据过滤）', async () => {
      mockInvoke.mockResolvedValue([{ id: 'not-a-uuid', name: '', css: '' }]);
      const result = await themeCssClient.list();
      expect(result).toEqual([]);
    });
  });

  // ─── delete ─────────────────────────────────────────────

  describe('delete', () => {
    it('成功时调用 theme_delete', async () => {
      mockInvoke.mockResolvedValue(undefined);
      await themeCssClient.delete(validPayload.id);
      expect(mockInvoke).toHaveBeenCalledWith('theme_delete', { id: validPayload.id });
    });

    it('失败时抛出错误', async () => {
      mockInvoke.mockRejectedValue(new Error('delete failed'));
      await expect(themeCssClient.delete(validPayload.id)).rejects.toThrow('delete failed');
    });
  });

  // ─── get ───────────────────────────────────────────────

  describe('get', () => {
    it('成功时返回经 zod 校验的对象', async () => {
      mockInvoke.mockResolvedValue(validPayload);
      const result = await themeCssClient.get(validPayload.id);
      expect(result).toEqual(validPayload);
      expect(mockInvoke).toHaveBeenCalledWith('theme_get', { id: validPayload.id });
    });

    it('后端返回 null 时返回 null', async () => {
      mockInvoke.mockResolvedValue(null);
      const result = await themeCssClient.get(validPayload.id);
      expect(result).toBeNull();
    });

    it('IPC 失败时返回 null（不抛）', async () => {
      mockInvoke.mockRejectedValue(new Error('IPC fail'));
      const result = await themeCssClient.get(validPayload.id);
      expect(result).toBeNull();
    });

    it('zod 校验失败时返回 null（脏数据过滤）', async () => {
      mockInvoke.mockResolvedValue({ id: 'bad-id', name: '', css: '' });
      const result = await themeCssClient.get('any-id');
      expect(result).toBeNull();
    });
  });
});
