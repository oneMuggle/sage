// @vitest-environment jsdom
/**
 * OrchestrationTab — Wave 3 P2-9 编排设置测试（原 GeneralTab.orch.test）。
 *
 * 编排 15 项已从 GeneralTab 拆出为独立 tab（2026-09-18 设置页 IA 治理）。
 * 只验证各输入渲染与部分更新契约：
 * updateSettings({ orch: { ...settings.orch, [key]: v } }) 必须保留其余 orch 键。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettings } from '../../../features/manage-settings/useSettings';
import { OrchestrationTab } from '../OrchestrationTab';

const mocks = vi.hoisted(() => ({
  updateSettings: vi.fn(),
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: vi.fn(),
}));

function mockSettings(orchOverride?: Partial<(typeof DEFAULT_SETTINGS)['orch']>): void {
  vi.mocked(useSettings).mockReturnValue({
    settings: {
      ...DEFAULT_SETTINGS,
      orch: { ...DEFAULT_SETTINGS.orch, ...orchOverride },
    },
    isLoading: false,
    loadSettings: vi.fn().mockResolvedValue(undefined),
    updateSettings: mocks.updateSettings,
    resetSettings: vi.fn(),
  } as unknown as ReturnType<typeof useSettings>);
}

function renderTab(): void {
  render(<OrchestrationTab />);
}

beforeEach(() => {
  mockSettings();
  mocks.updateSettings.mockReset();
});

describe('OrchestrationTab 渲染', () => {
  it('渲染全部编排设置输入（数值/开关/文本）', () => {
    renderTab();
    expect(screen.getByTestId('orch-max-concurrent')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-aggregate')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-subagent-result')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-retries')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-lane-iterations')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-subagent-iterations')).toBeInTheDocument();
    // RD16 (round26): 后端键集全量对齐的最后两个旋钮
    expect(screen.getByTestId('orch-worktree-isolation')).toBeInTheDocument();
    expect(screen.getByTestId('orch-scratch-root')).toBeInTheDocument();
  });

  it('守门键默认值与后端 OrchSettings 对齐（RD15）', () => {
    renderTab();
    expect((screen.getByTestId('orch-run-token-budget') as HTMLInputElement).value).toBe('0');
    expect((screen.getByTestId('orch-run-wall-clock-limit') as HTMLInputElement).value).toBe('0');
    expect((screen.getByTestId('orch-subagent-task-timeout') as HTMLInputElement).value).toBe(
      '900',
    );
    expect((screen.getByTestId('orch-max-retry-of-chains') as HTMLInputElement).value).toBe('10');
  });
});

describe('OrchestrationTab 部分更新契约', () => {
  it('子代理迭代上限默认 10 (alpha.36)，修改后 updateSettings 保留其它键', () => {
    renderTab();

    const subagentInput = screen.getByTestId('orch-max-subagent-iterations') as HTMLInputElement;
    expect(subagentInput.value).toBe('10');

    fireEvent.change(subagentInput, { target: { value: '12' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        maxSubagentIterations: 12,
        maxLaneIterations: 12, // 保留其余键（部分更新契约）
        maxRetries: 2,
      }),
    });
  });

  it('修改数值调 updateSettings 且保留其余 orch 键', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-max-retries'), { target: { value: '5' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ maxRetries: 5, maxConcurrentSubagents: 4 }),
    });
  });

  it('清空输入不提交 0 — 防 Semaphore(0) 编排挂死', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-max-concurrent'), { target: { value: '' } });
    expect(mocks.updateSettings).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId('orch-max-aggregate'), { target: { value: '' } });
    expect(mocks.updateSettings).not.toHaveBeenCalled();
  });

  it('并发数为 0 时不提交 — 防 Semaphore(0) 编排挂死', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-max-concurrent'), { target: { value: '0' } });
    expect(mocks.updateSettings).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId('orch-max-concurrent'), { target: { value: '1' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ maxConcurrentSubagents: 1 }),
    });
  });

  it('墙钟上限修改走部分更新契约（RD15）', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-run-wall-clock-limit'), { target: { value: '45' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        runWallClockLimitMinutes: 45,
        maxRetryOfChains: 10, // 保留其余键（部分更新契约）
      }),
    });
  });

  it('单任务超时与重派链上限修改走部分更新契约（RD15）', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-subagent-task-timeout'), {
      target: { value: '300' },
    });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ subagentTaskTimeoutS: 300 }),
    });

    fireEvent.change(screen.getByTestId('orch-max-retry-of-chains'), { target: { value: '5' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ maxRetryOfChains: 5 }),
    });
  });

  it('worktree 隔离开关默认关，切换走部分更新契约（RD16）', () => {
    renderTab();

    const toggle = screen.getByTestId('orch-worktree-isolation');
    fireEvent.click(toggle);
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        worktreeIsolation: true,
        maxRetryOfChains: 10, // 保留其余键（部分更新契约）
      }),
    });
  });

  it('scratch 根目录名默认 orch_scratch，修改走部分更新契约，空输入不提交（RD16）', () => {
    renderTab();

    const input = screen.getByTestId('orch-scratch-root') as HTMLInputElement;
    expect(input.value).toBe('orch_scratch');

    fireEvent.change(input, { target: { value: 'my_scratch' } });
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ scratchRoot: 'my_scratch' }),
    });

    fireEvent.change(input, { target: { value: '   ' } });
    expect(mocks.updateSettings).toHaveBeenCalledTimes(1); // 空白输入未追加提交
  });
});

// ============================================================================
// Round 3 (2026-09-19): 计划前置旋钮（orch-plan-preflight / orch-plan-scout）
// —— 原 main 侧 GeneralTab.orch.test 用例, 随编排段迁移至此。
// ============================================================================

describe('OrchestrationTab — 计划前置旋钮 (Round 3)', () => {
  it('澄清/侦察两个开关默认渲染', () => {
    renderTab();
    expect(screen.getByTestId('orch-plan-preflight')).toBeInTheDocument();
    expect(screen.getByTestId('orch-plan-scout')).toBeInTheDocument();
  });

  it('澄清开关默认开，关闭走部分更新契约', () => {
    renderTab();

    fireEvent.click(screen.getByTestId('orch-plan-preflight'));
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        planPreflightEnabled: false,
        maxRetryOfChains: 10, // 保留其余键（部分更新契约）
      }),
    });
  });

  it('侦察开关默认开，关闭走部分更新契约', () => {
    renderTab();

    fireEvent.click(screen.getByTestId('orch-plan-scout'));
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        planScoutEnabled: false,
        maxRetryOfChains: 10, // 保留其余键（部分更新契约）
      }),
    });
  });
});
