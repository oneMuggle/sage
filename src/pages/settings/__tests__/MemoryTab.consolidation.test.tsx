/**
 * R17-B: MemoryTab 记忆固化卡交互测试。
 *
 * memoryApi 与 desktopInvoke 模块级 mock；点击「立即固化」→ 结果回显 /
 * 失败 toast。embedder 状态走真实 invoke mock（返回 null 即可）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MemoryTab } from '../MemoryTab';

const runConsolidationMock = vi.fn();

vi.mock('../../../shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/api')>();
  return {
    ...actual,
    memoryApi: {
      ...actual.memoryApi,
      runConsolidation: (...args: unknown[]) => runConsolidationMock(...args),
    },
  };
});

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryTab />
    </I18nProvider>,
  );
}

describe('MemoryTab 记忆固化卡 (R17-B)', () => {
  beforeEach(() => {
    runConsolidationMock.mockReset();
    invokeMock.mockReset();
    invokeMock.mockResolvedValue(null);
  });

  it('runs consolidation and shows the result summary', async () => {
    runConsolidationMock.mockResolvedValue({ promoted: 2, decayed: 5, total: 7 });

    renderTab();
    fireEvent.click(screen.getByTestId('memory-consolidation-run'));

    await waitFor(() =>
      expect(screen.getByTestId('memory-consolidation-result')).toHaveTextContent(
        /晋升 2 条 · 衰减 5 条/,
      ),
    );
    expect(toast.success).toHaveBeenCalledWith('固化完成：晋升 2 条，衰减 5 条');
  });

  it('shows an error toast when consolidation fails', async () => {
    runConsolidationMock.mockRejectedValue(new Error('后端 503'));

    renderTab();
    fireEvent.click(screen.getByTestId('memory-consolidation-run'));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('固化失败: 后端 503'));
    expect(screen.queryByTestId('memory-consolidation-result')).not.toBeInTheDocument();
  });

  it('disables the button while consolidation is running', async () => {
    let resolveRun: (v: unknown) => void = () => undefined;
    runConsolidationMock.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      }),
    );

    renderTab();
    const button = screen.getByTestId('memory-consolidation-run');
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(screen.getByText('固化中...')).toBeInTheDocument();

    resolveRun({ promoted: 0, decayed: 0, total: 0 });
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
