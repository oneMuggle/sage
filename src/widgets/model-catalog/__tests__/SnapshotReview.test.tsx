/**
 * SnapshotReview 测试 (Task 6, 2026-09-15)
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../../../entities/model-catalog/api';
import { I18nProvider } from '../../../shared/lib/i18n';

// 路径修正: __tests__ 在 src/widgets/model-catalog/__tests__/, 需 ../../../ 才能到 src/。
// (SnapshotReview 组件自身用 ../../ 因为它在 src/widgets/model-catalog/, 仅 2 层。)
vi.mock('../../../entities/model-catalog/api', () => ({
  listSnapshots: vi.fn(),
  getDiff: vi.fn(),
  apply: vi.fn(),
  ignore: vi.fn(),
}));

beforeEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    backendRequest: async () => null,
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SnapshotReview', () => {
  it('requires review before applying imported data', async () => {
    vi.mocked(api.getDiff).mockResolvedValue([
      {
        id: 'item-1',
        base_revision: 0,
        before: null,
        after: {
          model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
          native: 200000,
          price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
        candidate: {
          model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
          native: 200000,
          price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
        clear_fields: [],
        classification: 'new',
        status: 'pending',
      },
    ]);

    const { SnapshotReview } = await import('../SnapshotReview');
    render(
      <I18nProvider defaultLocale="zh">
        <SnapshotReview snapshotId="synthetic-snapshot" />
      </I18nProvider>,
    );
    expect(await screen.findByText('待审核')).toBeVisible();
    expect(screen.getByRole('button', { name: '应用所选字段' })).toBeEnabled();
  });

  it('加载失败时显示空态, 按钮不可点击', async () => {
    vi.mocked(api.getDiff).mockRejectedValue(new Error('network error'));

    const { SnapshotReview } = await import('../SnapshotReview');
    render(
      <I18nProvider defaultLocale="zh">
        <SnapshotReview snapshotId="synthetic-snapshot" />
      </I18nProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/加载失败/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: '应用所选字段' })).toBeDisabled();
  });
});
