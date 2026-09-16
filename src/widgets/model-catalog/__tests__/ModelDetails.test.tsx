/**
 * ModelDetails 行为测试。
 *
 * - revision 状态归 ModelDetails 内部管理, 防止跨模型 token 泄漏
 * - 探测成功后应刷新 effective
 * - 409 后应刷新 effective 拿回最新 revision + 字段
 * - delete 返回的 revision 是 monotonic tombstone (current+1), 不是 0
 */
/* eslint-disable import/order -- test fixture (vi.hoisted + parent type import require this exact ordering) */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CandidateModel, EffectiveModel } from '../../../entities/model-catalog/types';

const mocks = vi.hoisted(() => ({
  getEffective: vi.fn(),
  setOverride: vi.fn(),
  deleteOverride: vi.fn(),
  probeModel: vi.fn(),
}));

vi.mock('../../../entities/model-catalog/api', () => mocks);

import { ModelDetails } from '../ModelDetails';

const item: CandidateModel = {
  model_key: { provider: 'openai', model_id: 'gpt-4o-mini' },
  native: 128000,
  service: null,
  price: { input_per_million: '0.15', output_per_million: '0.6', currency: 'USD' },
  capabilities: null,
  architecture: null,
  quantization: null,
  source: 'builtin',
  source_updated_at: null,
  pricing_scope: 'base',
};

const effective: EffectiveModel = {
  limits: { native: 128000, service: 64000 },
  price: { input_per_million: '0.15', output_per_million: '0.6', currency: 'USD' },
  provenance: {
    native: 'user_override',
    service: 'builtin',
    'price.input_per_million': 'builtin',
  },
  revision: 7,
};

function renderDetails(endpointId = 'endpoint-1') {
  const onStatusChange = vi.fn();
  const onReload = vi.fn().mockResolvedValue(undefined);
  render(
    <ModelDetails
      item={item}
      endpointId={endpointId}
      onStatusChange={onStatusChange}
      onReload={onReload}
    />,
  );
  return { onReload, onStatusChange };
}

describe('ModelDetails', () => {
  beforeEach(() => {
    mocks.getEffective.mockResolvedValue(effective);
    mocks.setOverride.mockResolvedValue({ revision: 8 });
    // Tombstone semantics: delete 返回 current+1 (=8), 不是 0
    mocks.deleteOverride.mockResolvedValue({ revision: 8 });
    mocks.probeModel.mockResolvedValue({
      status: 'unsupported',
      adapter: 'openai',
      data: null,
      error: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('loads effective revision and sends it with a saved override', async () => {
    renderDetails();

    await waitFor(() =>
      expect(mocks.getEffective).toHaveBeenCalledWith('endpoint-1', 'gpt-4o-mini'),
    );
    fireEvent.change(screen.getByTestId('override-native'), { target: { value: '8192' } });
    fireEvent.click(screen.getByTestId('override-save'));

    await waitFor(() => {
      expect(mocks.setOverride).toHaveBeenCalledWith(
        'endpoint-1',
        'gpt-4o-mini',
        { native: 8192 },
        7,
      );
    });
    // 后续 save 应使用新 revision (8), 验证内部状态确实更新
    fireEvent.change(screen.getByTestId('override-native'), { target: { value: '16384' } });
    fireEvent.click(screen.getByTestId('override-save'));
    await waitFor(() => {
      expect(mocks.setOverride).toHaveBeenLastCalledWith(
        'endpoint-1',
        'gpt-4o-mini',
        { native: 16384 },
        8,
      );
    });
  });

  it('restores inheritance with the effective revision and reloads the catalog', async () => {
    const { onReload } = renderDetails();

    expect(await screen.findByTestId('override-restore')).toBeEnabled();
    fireEvent.click(screen.getByTestId('override-restore'));

    await waitFor(() => {
      expect(mocks.deleteOverride).toHaveBeenCalledWith('endpoint-1', 'gpt-4o-mini', 7);
    });
    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it('refreshes effective after a successful probe', async () => {
    mocks.probeModel.mockResolvedValue({
      status: 'success',
      adapter: 'openai',
      data: { service: 32000 },
      error: null,
    });
    // 第二次 getEffective (probe 后) 返回更新的 revision
    mocks.getEffective
      .mockResolvedValueOnce(effective)
      .mockResolvedValueOnce({ ...effective, limits: { ...effective.limits, service: 32000 } });

    renderDetails();
    await screen.findByTestId('model-details-probe');

    fireEvent.click(screen.getByTestId('model-details-probe'));

    await waitFor(() => {
      expect(mocks.probeModel).toHaveBeenCalledWith('endpoint-1', 'gpt-4o-mini');
    });
    // 探测成功后必须再拉一次 effective (后端把探测层写入 effective_data)
    await waitFor(() => expect(mocks.getEffective).toHaveBeenCalledTimes(2));
  });

  it('shows a stale revision error when saving fails with 409 and refetches', async () => {
    mocks.setOverride.mockRejectedValue(new Error('HTTP 409: stale revision'));
    renderDetails();

    await screen.findByTestId('override-save');
    fireEvent.change(screen.getByTestId('override-native'), { target: { value: '8192' } });
    fireEvent.click(screen.getByTestId('override-save'));

    expect(await screen.findByRole('alert')).toHaveTextContent('字段已被其他进程修改');
    // 409 后应自动刷新 effective, 拿回最新 revision + 别人改的值
    await waitFor(() => expect(mocks.getEffective).toHaveBeenCalledTimes(2));
  });

  it('disables endpoint actions and skips effective loading without an endpoint', async () => {
    renderDetails('');

    expect(screen.getByTestId('model-details-probe')).toBeDisabled();
    expect(screen.getByTestId('override-save')).toBeDisabled();
    expect(mocks.getEffective).not.toHaveBeenCalled();
  });
});
