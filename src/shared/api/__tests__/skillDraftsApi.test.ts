/**
 * r85: skillDraftsApi 单元测试——list/approve/reject。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../utils', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    handleApiError: (error: unknown) => error,
    withRetry: async (fn: () => Promise<unknown>) => fn(),
  };
});

import { skillDraftsApi } from '../skillDraftsApi';

beforeEach(() => { mockInvoke.mockReset(); });

describe('skillDraftsApi', () => {
  it('list() defaults to pending status', async () => {
    mockInvoke.mockResolvedValueOnce({ drafts: [] });
    await skillDraftsApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('list_skill_drafts', { status: 'pending' });
  });

  it('list() passes custom status', async () => {
    mockInvoke.mockResolvedValueOnce({ drafts: [{ id: 'd1' }] });
    await skillDraftsApi.list('approved');
    expect(mockInvoke).toHaveBeenCalledWith('list_skill_drafts', { status: 'approved' });
  });

  it('approve() passes draft_id', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await skillDraftsApi.approve('d1');
    expect(mockInvoke).toHaveBeenCalledWith('approve_skill_draft', { draft_id: 'd1' });
  });

  it('reject() passes draft_id', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await skillDraftsApi.reject('d1');
    expect(mockInvoke).toHaveBeenCalledWith('reject_skill_draft', { draft_id: 'd1' });
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('backend down'));
    await expect(skillDraftsApi.list()).rejects.toThrow('backend down');
  });
});
