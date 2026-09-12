/**
 * R17-A1: skillsApi pin / 固化巡检（consolidation）封装测试。
 *
 * mock desktopInvoke.invoke，验证 IPC 通道名与参数形态、
 * 以及后端错误经 handleApiError 的结构化透出。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { skillsApi } from '../skillsApi';

describe('skillsApi pin / consolidation (R17-A1)', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('pinSkill routes through pin_skill with (name, pinned)', async () => {
    mockInvoke.mockResolvedValue({ name: 'search', pinned: true });

    await expect(skillsApi.pinSkill('search', true)).resolves.toEqual({
      name: 'search',
      pinned: true,
    });
    expect(mockInvoke).toHaveBeenCalledWith('pin_skill', { name: 'search', pinned: true });
  });

  it('scanConsolidation defaults autoDraft=true', async () => {
    mockInvoke.mockResolvedValue({ suggestions: [], scanned: 7, drafts_created: 0 });

    await expect(skillsApi.scanConsolidation()).resolves.toMatchObject({ scanned: 7 });
    expect(mockInvoke).toHaveBeenCalledWith('skills_consolidation_scan', { autoDraft: true });
  });

  it('scanConsolidation forwards autoDraft=false', async () => {
    mockInvoke.mockResolvedValue({ suggestions: [], scanned: 7, drafts_created: 0 });

    await skillsApi.scanConsolidation(false);
    expect(mockInvoke).toHaveBeenCalledWith('skills_consolidation_scan', { autoDraft: false });
  });

  it('getConsolidationSuggestions defaults limit=50', async () => {
    mockInvoke.mockResolvedValue([
      { skill_names: ['old-skill'], suggestion: { reason: 'stale' }, created_at: 1 },
    ]);

    await expect(skillsApi.getConsolidationSuggestions()).resolves.toHaveLength(1);
    expect(mockInvoke).toHaveBeenCalledWith('skills_consolidation_suggestions', { limit: 50 });
  });

  it('acceptConsolidation routes skillNames through skills_consolidation_accept', async () => {
    mockInvoke.mockResolvedValue({
      archived: ['a', 'b'],
      skipped_pinned: ['p'],
      missing: ['x'],
    });

    await expect(skillsApi.acceptConsolidation(['a', 'b', 'p', 'x'])).resolves.toEqual({
      archived: ['a', 'b'],
      skipped_pinned: ['p'],
      missing: ['x'],
    });
    expect(mockInvoke).toHaveBeenCalledWith('skills_consolidation_accept', {
      skillNames: ['a', 'b', 'p', 'x'],
    });
  });

  it('surfaces backend errors as structured ApiException', { timeout: 20_000 }, async () => {
    mockInvoke.mockRejectedValue(new Error('Backend POST /skills/consolidation/accept → 400: {}'));

    // withRetry 会先重试数次再放行，超时需覆盖重试总时长
    await expect(skillsApi.acceptConsolidation(['x'])).rejects.toThrow(/400/);
  });
});
